// Test: can a Virtual Output send a LONG text (Daikin tokens are ~1000+ chars) and can
// the Content-Type be overridden with multiple headers?
//
// Txt1 = 1500 characters + "-<counter>", changing every 20 s.
//
// Virtual Output        Address: https://httpbin.org
// └─ Virtual Output Command (input = Program Txt1)
//      "Als digitale uitgang gebruiken": OFF
//      Commando bij AAN:      /post
//      HTTP methode bij AAN:  POST
//      HTTP header bij AAN:   Content-Type: application/x-www-form-urlencoded\r\nAuthorization: Bearer <v>
//      HTTP body bij AAN:     grant_type=refresh_token&refresh_token=<v>
//      HTTP antwoord opslaan: votest.txt
//
// Check in the Loxone network monitor: Content-Length (~1560 expected), how many
// Content-Type headers are sent, and whether the Authorization header is complete.

char text[1600];
int i = 0;
int k;

for (k = 0; k < 1500; k++) {
	text[k] = 'A' + (k % 26);
}

while (TRUE) {
	i = i + 1;
	sprintf(text + 1500, "-%d", i);
	setoutputtext(0, text);
	sleep(20000);
}
