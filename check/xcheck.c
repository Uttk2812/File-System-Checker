#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdbool.h>

#include "xcheck.h"

dinode *get_nth_inode(int n);
dirent *get_nth_dirent(dinode *dinode_p, int n);
char *get_bitmap();

bool is_nth_bit_1(void *bitmap, int n);
void set_nth_bit_0(void *bitmap, int n);
void set_nth_bit_1(void *bitmap, int n);
bool is_addr_in_bounds(u32 addr);

void *file_bytes;
bool any_errors = false;

void report_check(const char *desc, bool condition) {
    if (condition) {
        printf("[PASS] %s\n", desc);
    } else {
        printf("[FAIL] %s\n", desc);
        any_errors = true;
    }
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: xcheck <file_system_image>\n");
        exit(1);
    }
    int fd = open(argv[1], O_RDONLY);
    if (fd < 0) {
        perror("could not open image");
        exit(1);
    }
    struct stat statbuf;
    assert(0 == fstat(fd, &statbuf));
    file_bytes = mmap(NULL, statbuf.st_size, PROT_READ, MAP_SHARED, fd, 0);
    assert(file_bytes != MAP_FAILED);
    close(fd);

    u32 direct_addrs[FSSIZE];
    u32 indirect_addrs[FSSIZE];
    int num_direct_addrs = 0, num_indirect_addrs = 0;
    u8 used_inodes_bitmap[NINODES / 8] = {0};
    u8 inode_references[NINODES] = {0};

    // Check inode types
    for (int i = 0; i < NINODES; i++) {
        dinode *ip = get_nth_inode(i);
        u16 type = xshort(ip->type);
        report_check("Inode type check", type == 0 || type == T_DIR || type == T_FILE || type == T_DEV);
    }

    inode_references[1]++;
    for (int i = 0; i < NINODES; i++) {
        dinode *ip = get_nth_inode(i);
        u16 type = xshort(ip->type);
        if (type == 0) continue;

        if (type == T_DIR) {
            for (int j = 2; j < BSIZE / sizeof(dirent); j++) {
                dirent *de = get_nth_dirent(ip, j);
                u16 inum = xshort(de->inum);
                if (inum != 0) inode_references[inum]++;
            }
        }

        set_nth_bit_1(used_inodes_bitmap, i);

        for (int j = 0; j < NDIRECT; j++) {
            u32 addr = xint(ip->addrs[j]);
            if (addr != 0) {
                direct_addrs[num_direct_addrs++] = addr;
            }
        }

        u32 indirect_addr = xint(ip->addrs[NDIRECT]);
        if (indirect_addr != 0) {
            indirect_addrs[num_indirect_addrs++] = indirect_addr;
            if (is_addr_in_bounds(indirect_addr)) {
                u32 *block = file_bytes + indirect_addr * BSIZE;
                for (int j = 0; j < BSIZE / sizeof(u32); j++) {
                    u32 addr = xint(block[j]);
                    if (addr != 0) indirect_addrs[num_indirect_addrs++] = addr;
                }
            }
        }
    }

    for (int i = 0; i < num_direct_addrs; i++) {
        report_check("Direct address bounds check", is_addr_in_bounds(direct_addrs[i]));
    }
    for (int i = 0; i < num_indirect_addrs; i++) {
        report_check("Indirect address bounds check", is_addr_in_bounds(indirect_addrs[i]));
    }

    dinode *root_ip = get_nth_inode(1);
    dirent *dp0 = get_nth_dirent(root_ip, 0);
    dirent *dp1 = get_nth_dirent(root_ip, 1);
    report_check("Root directory type",
                 xshort(root_ip->type) == T_DIR &&
                 xshort(dp0->inum) == 1 && xshort(dp1->inum) == 1);

    for (int i = 0; i < NINODES; i++) {
        dinode *ip = get_nth_inode(i);
        if (xshort(ip->type) == T_DIR) {
            dp0 = get_nth_dirent(ip, 0);
            dp1 = get_nth_dirent(ip, 1);
            report_check("Directory format check",
                         xshort(dp0->inum) == i &&
                         strcmp(dp0->name, ".") == 0 &&
                         strcmp(dp1->name, "..") == 0);
        }
    }

    char *bitmap = file_bytes + BSIZE * BMAPSTART;
    for (int i = 0; i < num_direct_addrs; i++) {
        report_check("Bitmap direct use match", is_nth_bit_1(bitmap, direct_addrs[i]));
    }
    for (int i = 0; i < num_indirect_addrs; i++) {
        report_check("Bitmap indirect use match", is_nth_bit_1(bitmap, indirect_addrs[i]));
    }

    u8 used_bitmap[BSIZE / 8];
    memcpy(used_bitmap, bitmap, BSIZE / 8);
    for (int i = 0; i < num_direct_addrs; i++) set_nth_bit_0(used_bitmap, direct_addrs[i]);
    for (int i = 0; i < num_indirect_addrs; i++) set_nth_bit_0(used_bitmap, indirect_addrs[i]);
    for (int i = 0; i < BSIZE / 8; i++) {
        report_check("Bitmap unused block check", used_bitmap[i] == 0);
    }

    for (int i = 0; i < NINODES; i++) {
        bool used = is_nth_bit_1(used_inodes_bitmap, i);
        bool refd = inode_references[i] > 0;
        report_check("Inode used but not found", !(used && !refd));
        report_check("Inode referenced but marked free", !(!used && refd));
    }

    for (int i = 0; i < NINODES; i++) {
        dinode *ip = get_nth_inode(i);
        if (xshort(ip->type) == T_FILE) {
            report_check("File ref count", xshort(ip->nlink) == inode_references[i]);
        }
    }

    for (int i = 0; i < NINODES; i++) {
        dinode *ip = get_nth_inode(i);
        if (xshort(ip->type) == T_DIR) {
            report_check("Directory appears once", xshort(ip->nlink) <= 1 && inode_references[i] <= 1);
        }
    }

    assert(0 == munmap(file_bytes, statbuf.st_size));
    if (any_errors) {
        printf("\nSome checks failed.\n");
        return 1;
    } else {
        printf("\nAll checks passed successfully.\n");
        return 0;
    }
}

char *get_bitmap() { return file_bytes + BSIZE * BMAPSTART; }

bool is_nth_bit_1(void *bitmap, int n) {
    u8 byte = ((u8 *)bitmap)[n / 8];
    return ((byte & (0x1 << (n % 8))) > 0);
}

bool is_addr_in_bounds(u32 addr) {
    return addr == 0 || (addr >= DATASTART && addr < FSSIZE);
}

void set_nth_bit_0(void *bitmap, int n) {
    ((u8 *)bitmap)[n / 8] &= ~(0x1 << (n % 8));
}

void set_nth_bit_1(void *bitmap, int n) {
    ((u8 *)bitmap)[n / 8] |= (0x1 << (n % 8));
}

dinode *get_nth_inode(int n) {
    assert(n >= 0 && n < NINODES);
    return (dinode *)(file_bytes + INODESTART * BSIZE + n * sizeof(dinode));
}

dirent *get_nth_dirent(dinode *inode_p, int n) {
    assert(n >= 0);
    assert(xshort(inode_p->type) == T_DIR);
    return (dirent *)(file_bytes + xshort(inode_p->addrs[0]) * BSIZE + n * sizeof(dirent));
}
