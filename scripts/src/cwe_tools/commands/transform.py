from cyclopts import App

# Reserved for parameterized one-off transformations (for example future
# buy-package scaling) that do not belong to deterministic generation.
app = App(name="transform", help="Run parameterized Victoria 3 transformations.")
