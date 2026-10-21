// Test: can a PicoC program read a saved Virtual Output response from the SD card?
// Use a SEPARATE program block, so a missing file API can't break other tests.
//
// Txt1 = first 250 characters of /user/common/votest.txt (or an error message)
// Txt2 = total number of bytes read
// Re-reads every 30 s.

char buf[260];
char info[60];
FILE *f;
int total;
int n;

while (TRUE) {
	f = fopen("/user/common/votest.txt", "r");
	if (f == 0) {
		setoutputtext(0, "fopen failed");
	} else {
		total = 0;
		n = fread(buf, 1, 250, f);
		buf[n] = 0;
		setoutputtext(0, buf);
		total = n;
		while (n > 0) {
			n = fread(info, 1, 50, f);
			total = total + n;
		}
		fclose(f);
		sprintf(info, "bytes=%d", total);
		setoutputtext(1, info);
	}
	sleep(30000);
}
