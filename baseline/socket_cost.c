#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char *end = NULL;
    unsigned long long requested = argc == 2 ? strtoull(argv[1], &end, 10) : 0;
    if (argc != 2 || !end || *end || requested < 1 || requested > 10000000) {
        fprintf(stderr, "usage: socket_cost MAX_SOCKETS (1..10000000)\n");
        return 2;
    }
    const size_t capacity = 200000;
    struct rlimit limit;
    if (getrlimit(RLIMIT_NOFILE, &limit) < 0) { perror("getrlimit"); return 1; }
    rlim_t needed = capacity + 32;
    limit.rlim_cur = limit.rlim_max < needed ? limit.rlim_max : needed;
    if (setrlimit(RLIMIT_NOFILE, &limit) < 0) { perror("setrlimit"); return 1; }
    int *fds = calloc(capacity, sizeof(int));
    if (!fds) { perror("calloc"); return 1; }
    size_t count = 0;
    int error = 0;
    printf("target=%llu\n", requested);
    fflush(stdout);
    while (count < requested) {
        if (count == capacity) {
            fprintf(stderr, "the descriptor array filled before memory ran out\n");
            error = EMFILE;
            break;
        }
        int fd = socket(AF_INET, SOCK_STREAM, 0); /* deliberately unbound */
        if (fd < 0) { error = errno; break; }
        fds[count++] = fd;
        if (count % 1000 == 0) { printf("count=%zu\n", count); fflush(stdout); }
    }
    printf("final_count=%zu errno=%d\n", count, error);
    fflush(stdout);
    for (size_t index = 0; index < count; index++) close(fds[index]);
    free(fds);
    return error ? 1 : 0;
}
