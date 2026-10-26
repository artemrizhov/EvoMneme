from dataclasses import dataclass, field


@dataclass
class Draft:
    reference: str = ''
    items: list = field(default_factory=list)

    def edit_reference(self, value):
        # Editing preserves exactly what the person entered.
        self.reference = value
