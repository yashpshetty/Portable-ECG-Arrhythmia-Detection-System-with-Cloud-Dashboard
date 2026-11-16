/*
 * ECG LIVE firmware - MSP-EXP430G2ET (MSP430G2553)
 * Same filter algorithm as the dataset test (360 Hz, HP ~0.5 Hz, LP ~40 Hz),
 * but the input now comes from the AD8232 through the ADC instead of the PC.
 *
 *   AD8232 OUTPUT -> P1.4 (A4)
 *   AD8232 LO+    -> P2.0
 *   AD8232 LO-    -> P2.1
 *   AD8232 3.3V -> 3V3, GND -> GND
 *
 * Output (USB backchannel, 115200 baud, 8N1), one line per sample:
 *      raw_adc,filtered,lead_off
 * No interrupts are used (timer flag is polled) so it builds with any
 * MSP430 compiler (CCS or msp430-elf-gcc).
 */
#include <msp430.h>

#define LO_PLUS   BIT0          /* P2.0 */
#define LO_MINUS  BIT1          /* P2.1 */

/* 16 MHz / 8 = 2 MHz timer clock; 2,000,000 / 5556 = 360.0 Hz */
#define TIMER_TOP 5555

/* ---- same filter constants as your tested program (fs = 360 Hz) ---- */
#define HP_ALPHA 32483L
#define LP_ALPHA 16286L

static long x_prev  = 0;
static long hp_prev = 0;
static long lp_prev = 0;
static int  first_sample = 1;

/* ------------------------------------------------------------ */
static void clock_init(void)
{
    WDTCTL  = WDTPW | WDTHOLD;
    DCOCTL  = 0;
    BCSCTL1 = CALBC1_16MHZ;
    DCOCTL  = CALDCO_16MHZ;
}

static void UART_init(void)
{
    P1SEL  |= BIT1 | BIT2;       /* P1.1 RXD, P1.2 TXD */
    P1SEL2 |= BIT1 | BIT2;

    UCA0CTL1 = UCSWRST | UCSSEL_2;   /* SMCLK = 16 MHz */
    UCA0BR0  = 138;                  /* 115200 baud */
    UCA0BR1  = 0;
    UCA0MCTL = UCBRS_7;
    UCA0CTL1 &= ~UCSWRST;
}

static void ADC_init(void)
{
    ADC10CTL1 = INCH_4;                          /* channel A4 = P1.4 */
    ADC10CTL0 = SREF_0 | ADC10SHT_2 | ADC10ON;   /* reference = VCC */
    ADC10AE0 |= BIT4;
}

static void timer_init(void)
{
    TACCR0  = TIMER_TOP;
    TACCTL0 = 0;                                  /* no interrupt, poll CCIFG */
    TACTL   = TASSEL_2 | ID_3 | MC_1 | TACLR;     /* SMCLK/8, up mode */
}

/* ------------------------------------------------------------ */
static void UART_send_char(char c)
{
    while (!(IFG2 & UCA0TXIFG)) { }
    UCA0TXBUF = c;
}

static void send_int(long value)
{
    char buffer[12];
    unsigned int i = 0;

    if (value == 0) { UART_send_char('0'); return; }
    if (value < 0)  { UART_send_char('-'); value = -value; }

    while (value > 0) {
        buffer[i++] = (char)('0' + (value % 10L));
        value /= 10L;
    }
    while (i > 0) {
        i--;
        UART_send_char(buffer[i]);
    }
}

static unsigned int ADC_read(void)
{
    ADC10CTL0 |= ENC | ADC10SC;
    while (ADC10CTL1 & ADC10BUSY) { }
    return ADC10MEM;
}

/* ------------------------------------------------------------
 * ECG FILTER (identical algorithm to the tested version)
 * ------------------------------------------------------------ */
static long ECG_filter(long x)
{
    long hp, lp;

    if (first_sample) {          /* avoid start-up spike */
        x_prev = x;
        first_sample = 0;
    }

    /* High-pass ~0.5 Hz */
    hp = (HP_ALPHA * (hp_prev + x - x_prev)) >> 15;

    /* Low-pass ~40 Hz */
    lp = ((LP_ALPHA * lp_prev) + ((32768L - LP_ALPHA) * hp)) >> 15;

    x_prev  = x;
    hp_prev = hp;
    lp_prev = lp;

    return lp;
}

/* ------------------------------------------------------------ */
int main(void)
{
    unsigned int raw;
    unsigned int lead_off;
    long filtered;

    clock_init();
    P2DIR &= ~(LO_PLUS | LO_MINUS);      /* lead-off pins = inputs */
    UART_init();
    ADC_init();
    timer_init();

    while (1)
    {
        /* wait for next 360 Hz tick */
        while (!(TACCTL0 & CCIFG)) { }
        TACCTL0 &= ~CCIFG;

        raw      = ADC_read();
        lead_off = (P2IN & (LO_PLUS | LO_MINUS)) ? 1 : 0;

        filtered = ECG_filter((long)raw);

        send_int((long)raw);       UART_send_char(',');
        send_int(filtered);        UART_send_char(',');
        UART_send_char((char)('0' + lead_off));
        UART_send_char('\r');      UART_send_char('\n');
    }
}
