"""
check if dir is writable
"""

import argparse
import os
from collections.abc import Sequence
from typing import Any, override


class WritableDirFolder(argparse.Action):
    """
    checks if this is a writeable folder OR file
    AND it works on nargs *
    stores a list[str] of the valid paths in the namespace
    """

    @override
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        if isinstance(values, str) or values is None:
            raise argparse.ArgumentError(self, f"{values} is not a list of writable dirs or files")
        else:
            # we loop through list (this is because of nargs *)
            for prospective_dir in values:
                # if valid and writeable (dir or file)
                if os.access(prospective_dir, os.W_OK):
                    # init new output array
                    out: list[str] = []
                    # if we have a previous list in the namespace extend current list
                    if isinstance(getattr(namespace, self.dest), list):
                        out.extend(getattr(namespace, self.dest))
                    # add the new dir to it
                    out.append(prospective_dir)
                    # and write that list back to the self.dest in the namespace
                    setattr(namespace, self.dest, out)
                else:
                    raise argparse.ArgumentError(self, f"{prospective_dir} is not a writable dir or file")


# __END__
