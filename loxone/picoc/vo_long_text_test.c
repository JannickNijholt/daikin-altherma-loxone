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

// Note: Loxone PicoC rejects pointer arithmetic on arrays (text + 1500), so the
// counter suffix is copied in character by character.

char text[1600];
char suffix[20];
int i = 0;
int k;
int j;

for (k = 0; k < 1500; k++) {
	text[k] = 'A' + (k % 26);
}

while (TRUE) {
	i = i + 1;
	sprintf(suffix, "-%d", i);
	j = 0;
	while (suffix[j] != 0) {
		text[1500 + j] = suffix[j];
		j = j + 1;
	}
	text[1500 + j] = 0;
	setoutputtext(0, text);
	sleep(20000);
}
