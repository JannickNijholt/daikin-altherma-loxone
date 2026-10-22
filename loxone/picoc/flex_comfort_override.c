// Touch Pure Flex -> temporary IRC override until 23:59:59 today, exactly like the Loxone app.
//
// The app sends (captured from the web interface):
//   override/57648/<until>/<temp>     until = seconds since 2009 (UTC), e.g. 561938399 = 22-10-2026 23:59:59 CEST
//   stopoverride                      ends it early
// The comfort temperature itself is never changed; the override ends by itself.
//
// Wiring:
//   Touch Pure Flex button:  VALUESELECT(Temp;I1;;19;23;0.5;°)    (Temp = this Program block)
//   Txt1 -> Virtual Output Command (analog, not digital), command for ON:
//           /jdev/sps/io/Klimaat%201e%20verdieping/override/57648/<v>
//
// Txt1 becomes "<until>/<temp>", e.g. "561938399/22.5". A new day gives a new <until>, so the
// command text always changes and is always sent. Written without user functions or pointer
// arithmetic: the Loxone PicoC interpreter rejects those.

float temp;
float last = -1;
unsigned int t;
unsigned int until;
int h;
int m;
int s;
char cmd[64];

while (TRUE) {
	temp = getinput(0);
	if (temp >= 15 && temp <= 30 && temp != last) {
		t = getcurrenttime();
		h = gethour(t, 1);
		m = getminute(t, 1);
		s = getsecond(t, 1);
		until = t + (23 - h) * 3600 + (59 - m) * 60 + (59 - s);
		sprintf(cmd, "%u/%.1f", until, temp);
		setoutputtext(0, cmd);
		last = temp;
	}
	sleep(500);
}
