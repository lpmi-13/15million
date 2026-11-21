#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    unsigned long index = 0;
    if (argc == 2) {
        char *end = NULL;
        index = strtoul(argv[1], &end, 10);
        if (!end || *end || index < 1 || index > 15000000) {
            fprintf(stderr, "usage: server [INDEX (1..15000000)]\n");
            return 2;
        }
    } else if (argc != 1) {
        fprintf(stderr, "usage: server [INDEX (1..15000000)]\n");
        return 2;
    }

    int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) { perror("socket"); return 1; }

    if (argc == 2) {
        struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons(8081)};
        // TODO (step 4): Shift the base address by index, as in the article.
        address.sin_addr.s_addr = htonl(0x7f000001u);
        if (bind(server, (struct sockaddr *)&address, sizeof(address)) < 0) {
            perror("bind"); return 1;
        }
    }

    // TODO (step 1): Call listen(server, 128) here and handle its error.

    if (argc == 1) {
        struct sockaddr_in address;
        socklen_t length = sizeof(address);
        if (getsockname(server, (struct sockaddr *)&address, &length) < 0) {
            perror("getsockname"); return 1;
        }
        unsigned port = ntohs(address.sin_port);
        printf("port=%u\n", port);
        fflush(stdout);
        const char *port_file = getenv("PORT_FILE");
        if (port_file) {
            FILE *file = fopen(port_file, "w");
            if (!file) { perror("PORT_FILE"); return 1; }
            fprintf(file, "%u\n", port);
            fclose(file);
        }
    }

    const char *body = argc == 2 ? argv[1] : "ok";
    char response[96];
    int size = snprintf(response, sizeof(response),
                        "HTTP/1.0 200 OK\r\nContent-Length: %zu\r\n\r\n%s",
                        strlen(body), body);
    if (size < 0 || size >= (int)sizeof(response)) return 1;
    for (;;) {
        int client = accept(server, NULL, NULL);
        if (client < 0) {
            if (errno == EINTR) continue;
            perror("accept"); return 1;
        }
        char request[512];
        if (recv(client, request, sizeof(request), 0) > 0)
            send(client, response, (size_t)size, MSG_NOSIGNAL);
        close(client);
    }
}
