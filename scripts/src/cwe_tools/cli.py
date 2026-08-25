from cyclopts import App

from cwe_tools.commands.format import app as format_app
from cwe_tools.commands.generate import app as generate_app
from cwe_tools.commands.lint import app as lint_app
from cwe_tools.commands.parse import app as parse_app
from cwe_tools.commands.transform import app as transform_app
from cwe_tools.commands.validate import app as validate_app

app = App(
    name="cwe",
    help="Developer tooling for the CWE Modern Victoria 3 mod.",
    version="0.0.1",
)

app.command(generate_app)
app.command(format_app)
app.command(lint_app)
app.command(parse_app)
app.command(transform_app)
app.command(validate_app)


def main() -> None:
    app()
