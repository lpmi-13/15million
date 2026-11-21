#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

/* No argument: implicit bind. With an index: one loopback address per process. */
int main(int argc, char **argv) {
    char *end = NULL;
    unsigned long index = 0;
    if (argc == 2) index = strtoul(argv[1], &end, 10);
    if (argc > 2 || (argc == 2 && (!end || *end || index < 1 || index > 15000000))) {
        fprintf(stderr, "usage: server [INDEX (1..15000000)]\n");
        return 2;
    }
    int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) { perror("socket"); return 1; }
    if (argc == 2) {
        struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons(8081)};
        address.sin_addr.s_addr = htonl(0x7f000001u + (uint32_t)index);
        if (bind(server, (struct sockaddr *)&address, sizeof(address)) < 0) {
            perror("bind"); return 1;
        }
    }
    if (listen(server, 8) < 0) { perror("listen"); return 1; }
    const char *label = argc == 2 ? argv[1] : "ok";
    char reply[96];
    int size = snprintf(reply, sizeof(reply),
                        "HTTP/1.0 200 OK\r\nContent-Length: %zu\r\n\r\n%s",
                        strlen(label), label);
    if (size < 0 || size >= (int)sizeof(reply)) return 1;
    for (;;) {
        int client = accept(server, NULL, NULL);
        if (client < 0) {
            if (errno == EINTR) continue;
            perror("accept"); return 1;
        }
        char request[512];
        if (recv(client, request, sizeof(request), 0) > 0)
            send(client, reply, (size_t)size, MSG_NOSIGNAL);
        close(client);
    }
}
