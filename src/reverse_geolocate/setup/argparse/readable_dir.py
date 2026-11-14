"""
Check if dir is readable
"""

import argparse
import os
from collections.abc import Sequence
from typing import Any, override


class ReadableDir(argparse.Action):
    """
    custom define to check if it is a valid directory
    stores the path as str in the namespace
    """

    @override
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        prospective_dir = values
        if not isinstance(prospective_dir, str):
            raise argparse.ArgumentError(self, f"{prospective_dir} is not a readable dir")
        else:
            if not os.path.isdir(prospective_dir):
                raise argparse.ArgumentError(self, f"{prospective_dir} is not an existing directory")
            if os.access(prospective_dir, os.R_OK):
                setattr(namespace, self.dest, prospective_dir)
            else:
                raise argparse.ArgumentError(self, f"{prospective_dir} is not a readable dir")


# __END__
