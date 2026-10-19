If replacing ``exports/latest`` fails and the previous export cannot be
moved back, that tree is left at its recovery path and the error names both
locations instead of deleting it. Interrupting the final replacement restores
the previous export before propagating the interruption.
