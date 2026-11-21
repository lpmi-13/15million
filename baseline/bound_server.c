#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 4 || strlen(argv[3]) > 32) {
        fprintf(stderr, "usage: bound_server IP PORT ID (ID <= 32 bytes)\n");
        return 2;
    }
    struct addrinfo hints = {.ai_family = AF_UNSPEC, .ai_socktype = SOCK_STREAM,
                             .ai_flags = AI_NUMERICHOST | AI_NUMERICSERV};
    struct addrinfo *addresses = NULL;
    int code = getaddrinfo(argv[1], argv[2], &hints, &addresses);
    if (code) { fprintf(stderr, "address: %s\n", gai_strerror(code)); return 1; }
    int server = socket(addresses->ai_family, addresses->ai_socktype, addresses->ai_protocol);
    if (server < 0) { perror("socket"); return 1; }
    int reuse = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    if (bind(server, addresses->ai_addr, addresses->ai_addrlen) < 0) {
        perror("bind"); return 1;
    }
    freeaddrinfo(addresses);
    if (listen(server, 8) < 0) { perror("listen"); return 1; }
    char response[128];
    int size = snprintf(response, sizeof(response),
                        "HTTP/1.0 200 OK\r\nContent-Length: %zu\r\n\r\n%s",
                        strlen(argv[3]), argv[3]);
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
