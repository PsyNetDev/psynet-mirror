`conditional` now converts its condition's result with `bool()`, so a condition that returns, for example, a number or a list chooses a branch instead of raising an error.
