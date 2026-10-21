// Test: can ONE <v> carry both the Authorization header and a JSON body?
//
// Daikin commands need a changing token (header) and a value (body), but a Virtual
// Output command has only one <v>. Idea: header field = "<v>", body field empty,
// and <v> contains the headers, a blank line and the JSON body.
//
// Virtual Output        Address: https://httpbin.org
// └─ Virtual Output Command (input = Program Txt1)
//      "Als digitale uitgang gebruiken": OFF
//      Commando bij AAN:      /put
//      HTTP methode bij AAN:  PUT
//      HTTP header bij AAN:   <v>
//      HTTP body bij AAN:     (empty)
//      HTTP antwoord opslaan: the save path that worked
//
// Success = httpbin's reply shows "json": {"value": 21.5, "n": <counter>}
// and "Authorization": "Bearer TESTTOKEN-<counter>".

char text[300];
char body[80];
int i = 0;

while (TRUE) {
	i = i + 1;
	sprintf(body, "{\"value\": 21.5, \"n\": %d}", i);
	sprintf(text, "Authorization: Bearer TESTTOKEN-%d\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s", i, strlen(body), body);
	setoutputtext(0, text);
	sleep(20000);
}
