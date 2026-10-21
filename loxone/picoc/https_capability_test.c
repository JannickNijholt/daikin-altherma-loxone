// HTTPS capability test for a Loxone Miniserver (PicoC "Program" block).
//
// Question: can this Miniserver open an HTTPS connection from a program block?
// That decides whether the Daikin Onecta cloud API can be used from Loxone alone,
// because the Daikin API only accepts HTTPS.
//
// How to run:
//   1. Loxone Config: add a "Program" block, paste this code, save to the Miniserver.
//   2. Watch Txt1..Txt3 in Liveview (and Etxt if a step fails).
//   3. Report Txt1, Txt2, Txt3 and Etxt back.
//
// Txt1 = httpget results, Txt2 = stream results, Txt3 = last step started.
// The plain-HTTP tests are controls: if they fail, the test itself is broken
// (DNS/internet), not HTTPS. Written without user functions or ?: on purpose:
// the Loxone PicoC interpreter rejects some standard constructs.

char response[513];
char res1[300];
char res2[300];
char *r;
STREAM *s;
int n;

res1[0] = 0;
res2[0] = 0;

// 1. httpget over plain HTTP (control)
setoutputtext(2, "step 1 httpget http");
r = httpget("example.com", "/");
if (r != 0) {
	strcat(res1, "http:OK ");
	free(r);
} else {
	strcat(res1, "http:FAIL ");
}
setoutputtext(0, res1);

// 2. TCP stream on port 80 (control)
setoutputtext(2, "step 2 stream tcp80");
n = 0;
response[0] = 0;
s = stream_create("/dev/tcp/example.com/80", 0, 0);
if (s != 0) {
	stream_printf(s, "GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n");
	stream_flush(s);
	n = stream_read(s, response, 512, 5000);
	stream_close(s);
}
if (n > 7 && strncmp(response, "HTTP/1.", 7) == 0) {
	strcat(res2, "tcp80:OK ");
} else {
	strcat(res2, "tcp80:FAIL ");
}
setoutputtext(1, res2);

// 3-5. TLS stream candidates on port 443 (undocumented device paths)
setoutputtext(2, "step 3 stream tls");
n = 0;
response[0] = 0;
s = stream_create("/dev/tls/example.com/443", 0, 0);
if (s != 0) {
	stream_printf(s, "GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n");
	stream_flush(s);
	n = stream_read(s, response, 512, 5000);
	stream_close(s);
}
if (n > 7 && strncmp(response, "HTTP/1.", 7) == 0) {
	strcat(res2, "tls:OK ");
} else {
	strcat(res2, "tls:FAIL ");
}
setoutputtext(1, res2);

setoutputtext(2, "step 4 stream ssl");
n = 0;
response[0] = 0;
s = stream_create("/dev/ssl/example.com/443", 0, 0);
if (s != 0) {
	stream_printf(s, "GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n");
	stream_flush(s);
	n = stream_read(s, response, 512, 5000);
	stream_close(s);
}
if (n > 7 && strncmp(response, "HTTP/1.", 7) == 0) {
	strcat(res2, "ssl:OK ");
} else {
	strcat(res2, "ssl:FAIL ");
}
setoutputtext(1, res2);

setoutputtext(2, "step 5 stream tcps");
n = 0;
response[0] = 0;
s = stream_create("/dev/tcps/example.com/443", 0, 0);
if (s != 0) {
	stream_printf(s, "GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n");
	stream_flush(s);
	n = stream_read(s, response, 512, 5000);
	stream_close(s);
}
if (n > 7 && strncmp(response, "HTTP/1.", 7) == 0) {
	strcat(res2, "tcps:OK ");
} else {
	strcat(res2, "tcps:FAIL ");
}
setoutputtext(1, res2);

// 6. httpget over HTTPS (last: it hung on the first run, so it must not block the stream tests)
setoutputtext(2, "step 6 httpget https (may hang)");
r = httpget("https://example.com", "/");
if (r != 0) {
	strcat(res1, "https:OK ");
	free(r);
} else {
	strcat(res1, "https:FAIL ");
}
setoutputtext(0, res1);

setoutputtext(2, "done");
