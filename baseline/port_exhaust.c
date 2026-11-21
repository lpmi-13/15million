#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <unistd.h>

int main(void) {
    unsigned low = 0, high = 0;
    FILE *range = fopen("/proc/sys/net/ipv4/ip_local_port_range", "r");
    if (!range || fscanf(range, "%u %u", &low, &high) != 2 || high < low) {
        perror("ip_local_port_range"); return 1;
    }
    fclose(range);
    size_t maximum = (size_t)(high - low + 1) + 1024;
    if (maximum > 64000) maximum = 64000;
    struct rlimit limit;
    if (getrlimit(RLIMIT_NOFILE, &limit) < 0) { perror("getrlimit"); return 1; }
    rlim_t needed = maximum + 32;
    if (limit.rlim_cur < needed) {
        limit.rlim_cur = limit.rlim_max < needed ? limit.rlim_max : needed;
        if (setrlimit(RLIMIT_NOFILE, &limit) < 0) { perror("setrlimit"); return 1; }
    }
    if (limit.rlim_cur < needed) {
        fprintf(stderr, "RLIMIT_NOFILE is too low for port exhaustion\n"); return 2;
    }
    int *fds = calloc(maximum, sizeof(int));
    if (!fds) { perror("calloc"); return 1; }
    size_t count = 0;
    int failed_errno = 0;
    const char *syscall_name = "none";
    while (count < maximum) {
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) { failed_errno = errno; syscall_name = "socket"; break; }
        if (listen(fd, 1) < 0) {
            failed_errno = errno;
            syscall_name = "listen";
            close(fd);
            break;
        }
        fds[count++] = fd;
    }
    printf("{\"range_low\":%u,\"range_high\":%u,\"count\":%zu,"
           "\"maximum\":%zu,\"failed_syscall\":\"%s\",\"errno\":%d}\n",
           low, high, count, maximum, syscall_name, failed_errno);
    fflush(stdout);
    for (size_t index = 0; index < count; index++) close(fds[index]);
    free(fds);
    return failed_errno == EADDRINUSE && syscall_name[0] == 'l' ? 0 : 1;
}
