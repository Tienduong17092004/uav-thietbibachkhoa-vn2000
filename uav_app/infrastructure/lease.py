"""One application process per project, including launches on different ports."""
from pathlib import Path
import os


class ProjectLease:
    def __init__(self,root):
        self.handle=(Path(root)/'.uav_session.lock').open('a+b')
        self.handle.seek(0,2)
        if self.handle.tell()==0:
            self.handle.write(b'0');self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise ValueError('Dự án đang được một phiên ứng dụng khác mở. Hãy đóng phiên cũ trước.') from None

    def close(self):
        if self.handle.closed: return
        self.handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
        self.handle.close()
