// Test: can a Virtual Output command insert TEXT via <v> (header and body)?
//
// Outputs: O1 = counter (number, control), Txt1 = "abc123XYZ-<counter>" (text).
// Both change every 15 s, so Virtual Output commands connected to them fire.
//
// Loxone Config setup (see docs/loxone-only-feasibility.md):
//   Virtual Output        Address: http://<logger-ip>:8099   (tools/request_logger.py)
//   ├─ Command A (number, control): input = Program O1
//   │    "Als digitale uitgang gebruiken": OFF
//   │    Commando bij AAN: /num/<v>     HTTP methode bij AAN: POST
//   │    HTTP header bij AAN: X-Lox-Test: <v>
//   │    HTTP body bij AAN: token=<v>
//   │    HTTP antwoord opslaan: voA.txt
//   └─ Command B (text): input = Program Txt1
//        same as A but Commando bij AAN: /txt/<v> and HTTP antwoord opslaan: voB.txt
//
// The logger prints each request. If command B shows "abc123XYZ-…" in the path,
// header or body, Virtual Outputs can send dynamic text.

char text[64];
int i = 0;

while (TRUE) {
	i = i + 1;
	sprintf(text, "abc123XYZ-%d", i);
	setoutputtext(0, text);
	setoutput(0, i);
	sleep(15000);
}
