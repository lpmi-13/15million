#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    size_t maximum = argc == 2 ? strtoull(argv[1], NULL, 10) : 200000;
    if (maximum == 0 || maximum > 200000) return 2;
    struct rlimit limit;
    if (getrlimit(RLIMIT_NOFILE, &limit) < 0) { perror("getrlimit"); return 1; }
    rlim_t needed = maximum + 32;
    limit.rlim_cur = limit.rlim_max < needed ? limit.rlim_max : needed;
    if (setrlimit(RLIMIT_NOFILE, &limit) < 0) { perror("setrlimit"); return 1; }
    int *fds = calloc(maximum, sizeof(int));
    if (!fds) { perror("calloc"); return 1; }
    size_t count = 0;
    int error = 0;
    while (count < maximum) {
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
