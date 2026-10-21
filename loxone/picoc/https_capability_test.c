// HTTPS capability test for a Loxone Miniserver (PicoC "Program" block).
//
// Question: can this Miniserver open an HTTPS connection from a program block?
// That decides whether the Daikin Onecta cloud API can be used from Loxone alone,
// because the Daikin API only accepts HTTPS.
//
// How to run:
//   1. Loxone Config: add a "Program" block (Script), paste this code, save to the Miniserver.
//   2. Watch outputs TQ1..TQ3 in Liveview and the log (Monitor / def.log).
//   3. Report the TQ1/TQ2 lines back.
//
// Each line is "<test>: OK" when an HTTP response came back, otherwise "FAIL".
// The plain-HTTP tests are controls: if they fail, the test itself is broken
// (DNS/internet), not HTTPS.

char response[513];
char summary[400];
char line[100];

int looks_like_http(char *text)
{
	if (text == NULL) return 0;
	return strncmp(text, "HTTP/1.", 7) == 0 || strstr(text, "<html") != NULL || strstr(text, "<!doctype") != NULL;
}

void test_httpget(char *label, char *address)
{
	char *result = httpget(address, "/");
	sprintf(line, "%s: %s; ", label, looks_like_http(result) ? "OK" : "FAIL");
	printf("httpget %s -> %s", address, looks_like_http(result) ? "OK" : "FAIL");
	strcat(summary, line);
	if (result != NULL) free(result);
}

void test_stream(char *label, char *path)
{
	STREAM *stream = stream_create(path, 0, 0);
	int n = 0;
	response[0] = 0;
	if (stream != NULL) {
		stream_printf(stream, "GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n");
		stream_flush(stream);
		n = stream_read(stream, response, 512, 5000);
		if (n > 0) response[n] = 0;
		stream_close(stream);
	}
	sprintf(line, "%s: %s; ", label, (n > 0 && looks_like_http(response)) ? "OK" : (stream == NULL ? "NO-STREAM" : "FAIL"));
	printf("stream %s -> created=%d bytes=%d", path, stream != NULL, n);
	strcat(summary, line);
}

summary[0] = 0;
test_httpget("httpget-http(control)", "example.com");
test_httpget("httpget-https", "https://example.com");
setoutputtext(0, summary);

summary[0] = 0;
test_stream("tcp80(control)", "/dev/tcp/example.com/80");
test_stream("tls", "/dev/tls/example.com/443");
test_stream("ssl", "/dev/ssl/example.com/443");
test_stream("tcps", "/dev/tcps/example.com/443");
setoutputtext(1, summary);

setoutputtext(2, "done");
printf("HTTPS capability test done");
