// Test: can a PicoC program read a saved Virtual Output response, and write a file?
// Use a SEPARATE program block, so a missing file API can't break other tests.
//
// Txt1 = which candidate path opened + bytes read
// Txt2 = first 200 characters of that file
// Txt3 = write test: writes /user/common/lox_write_test.txt and reads it back
// Re-runs every 30 s.

char buf[210];
char info[120];
char back[60];
FILE *f;
int n;
int total;

while (TRUE) {
	strcpy(info, "no path opened");
	buf[0] = 0;

	f = fopen("/user/common/votest.txt", "r");
	if (f != 0) {
		strcpy(info, "/user/common/votest.txt");
	} else {
		f = fopen("user/common/votest.txt", "r");
		if (f != 0) {
			strcpy(info, "user/common/votest.txt");
		} else {
			f = fopen("/user/custom/votest.txt", "r");
			if (f != 0) {
				strcpy(info, "/user/custom/votest.txt");
			}
		}
	}

	if (f != 0) {
		n = fread(buf, 1, 200, f);
		buf[n] = 0;
		total = n;
		while (n > 0) {
			n = fread(back, 1, 50, f);
			total = total + n;
		}
		fclose(f);
		sprintf(back, " bytes=%d", total);
		strcat(info, back);
	}
	setoutputtext(0, info);
	setoutputtext(1, buf);

	f = fopen("/user/common/lox_write_test.txt", "w");
	if (f == 0) {
		setoutputtext(2, "write: fopen failed");
	} else {
		fprintf(f, "token-backup-test");
		fclose(f);
		back[0] = 0;
		f = fopen("/user/common/lox_write_test.txt", "r");
		if (f == 0) {
			setoutputtext(2, "write: ok, read back failed");
		} else {
			n = fread(back, 1, 50, f);
			back[n] = 0;
			fclose(f);
			sprintf(info, "write+read: %s", back);
			setoutputtext(2, info);
		}
	}
	sleep(30000);
}
