#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

int main(void) {
    int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) { perror("socket"); return 1; }
    /* Linux implicitly binds an unbound socket when listen is called. */
    if (listen(server, 16) < 0) { perror("listen"); return 1; }
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
    static const char response[] = "HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok";
    for (;;) {
        int client = accept(server, NULL, NULL);
        if (client < 0) {
            if (errno == EINTR) continue;
            perror("accept"); return 1;
        }
        char request[512];
        if (recv(client, request, sizeof(request), 0) > 0) {
            if (send(client, response, sizeof(response) - 1, MSG_NOSIGNAL) < 0)
                perror("send");
        }
        close(client);
    }
}
