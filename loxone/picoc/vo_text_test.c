// Test: can a Virtual Output command insert TEXT via <v> (header and body)?
//
// Loxone Config setup:
//   Virtual Output        Address: https://httpbin.org
//   └─ Virtual Output Command
//        "Als digitale uitgang gebruiken" (use as digital output): OFF
//        Commando bij AAN (command for ON):  /post
//        HTTP methode bij AAN:               POST
//        HTTP header bij AAN:                X-Lox-Test: <v>
//        HTTP body bij AAN:                  token=<v>
//        HTTP antwoord opslaan:              votest.txt
//   Program block with this code: connect Txt1 -> the Virtual Output Command.
//
// Then open http://<miniserver-ip>/votest.txt (log in with a Loxone user).
// httpbin echoes the request: if "abc123XYZ-…" appears under "form" and under
// "X-Lox-Test" in "headers", Virtual Outputs can send dynamic text.

char text[64];
int i = 0;

while (TRUE) {
	i = i + 1;
	sprintf(text, "abc123XYZ-%d", i);
	setoutputtext(0, text);
	sleep(15000);
}
