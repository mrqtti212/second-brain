from typing import Annotated

from pydantic import StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
