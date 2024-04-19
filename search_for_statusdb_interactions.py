import ast
import argparse
import csv
import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)


class Context:
    def __init__(
        self,
        file_name,
        line_number,
        object,
        argument,
        keyword_arguments,
        function_scope,
        class_scope,
    ):
        self.file_name = file_name
        self.line_number = line_number
        self.object = object
        self.argument = argument
        self.keyword_arguments = keyword_arguments
        self.function_scope = function_scope
        self.class_scope = class_scope

    def print(self):
        print(
            f"Function {self.object}({self.argument}) called with keyword argument {self.keyword_arguments} within {self.class_scope}:{self.function_scope} in {self.file_name}:{self.line_number}"
        )

    def to_key(self):
        return (
            self.file_name,
            self.class_scope if self.class_scope else "",
            self.function_scope if self.function_scope else "",
        )

    def has_variables(self):
        return "<variable:" in self.argument or "<variable:" in self.object


class ManualCuration(object):
    """Manual curation is used to track possible values for variables used for database name and view name"""

    def __init__(self, file_name):
        self.file_name = file_name
        self.fields = {}

    def parse(self):
        logger.debug(f"Parsing manual curation file {self.file_name}")
        df = pd.read_table(self.file_name, sep=",", header=0, comment="#")
        df = df.fillna("")

        for _, row in df.iterrows():
            key_t = tuple(row[["Path", "Class", "Function"]].values)
            val_t = tuple(
                row[
                    [
                        "Database_variable_name",
                        "Database_variable_value",
                        "View_variable_name",
                        "View_variable_value",
                    ]
                ].values
            )
            if key_t not in self.fields:
                self.fields[key_t] = []
            self.fields[key_t].append(val_t)

    def compare_against_manual_curation(self, context):
        new_contexts = []
        if context.to_key() in self.fields:
            for val_t in self.fields[context.to_key()]:
                if context.object == val_t[0] and context.argument == val_t[2]:
                    logger.debug(
                        f"Creating new context from manual curation for {val_t}"
                    )
                    new_contexts.append(
                        Context(
                            context.file_name,
                            context.line_number,
                            val_t[1],
                            val_t[3],
                            context.keyword_arguments,
                            context.function_scope,
                            context.class_scope,
                        )
                    )
        return new_contexts


class FunctionCallVisitor(ast.NodeVisitor):
    def __init__(self, target_function, file_name):
        self.target_function = target_function
        self.function_calls = []
        self.file_name = file_name
        self.current_function = None
        self.current_class = None
        self.prev_function = None

    def visit_ClassDef(self, node):
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = None

    def visit_FunctionDef(self, node):
        # Saving the previous function will allow tested functions
        # (functions defined within other function bodies) to be tracked up to 1 level
        self.prev_function = self.current_function
        self.current_function = node.name

        self.generic_visit(node)
        self.current_function = self.prev_function

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == self.target_function
        ):
            argument = ""
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    argument = f"<variable:{arg.id}>"
                elif isinstance(arg, ast.JoinedStr):
                    argument = self.handle_joined_str(arg)
                else:
                    argument = arg.value

            kw_arguments = [keyword.arg for keyword in node.keywords]

            # Try to figure out which database the view is called on
            if isinstance(node.func.value, ast.Name):
                # The function is called on a variable, this needs to be dealt with manually (manual curation file)
                object = f"<variable:{node.func.value.id}>"
            elif node.func.value.attr == "db":
                # Common name of object that should be considered a variable as well
                object = "<variable:db>"
            else:
                object = node.func.value.attr

            context = Context(
                file_name=self.file_name,
                line_number=node.lineno,
                object=object,
                argument=argument,
                keyword_arguments=kw_arguments,
                function_scope=self.current_function,
                class_scope=self.current_class,
            )
            self.function_calls.append(context)
        self.generic_visit(node)

    def handle_joined_str(self, arg):
        return "".join(
            [
                f"<variable:{value.value.id}>"
                if isinstance(value, ast.FormattedValue)
                else value.s
                for value in arg.values
            ]
        )


def check_file(file_name, target_function, manual_curator, suggestions_file=None):
    with open(file_name, "r") as f:
        source_code = f.read()
    tree = ast.parse(source_code)

    visitor = FunctionCallVisitor(target_function, file_name)
    visitor.visit(tree)
    for context in visitor.function_calls:
        extra_contexts = manual_curator.compare_against_manual_curation(context)
        if extra_contexts:
            for extra_context in extra_contexts:
                extra_context.print()
        elif context.has_variables():
            logger.warning(
                f"WARNING: Variable found in context {context.file_name}:{context.line_number} without matching manual curation, please add line(s) to manual curation on the following form: \n\t"
            )
            suggestion = f"{','.join(list(context.to_key()))},{context.object},"
            suggestion += (
                "---possible db value---"
                if "<variable:" in context.object
                else context.object
            )
            suggestion += f",{context.argument},"
            suggestion += (
                "---possible view value---"
                if "<variable:" in context.argument
                else context.argument
            )
            suggestion += "\n"
            logger.warning(suggestion)
            if suggestions_file:
                with open(suggestions_file, "a") as f:
                    f.write(suggestion)
        else:
            context.print()


def main(target_function, files, dirs, manual_curation_file, suggestions_file):
    manual_curator = ManualCuration(manual_curation_file)
    manual_curator.parse()

    for file_name in files:
        check_file(file_name, target_function, manual_curator, suggestions_file)

    # Recurse through directories
    for directory in dirs:
        for dirpath, dirs, files in os.walk(directory):
            for file_name in files:
                if file_name.endswith(".py"):
                    file_path = os.path.join(dirpath, file_name)
                    check_file(
                        file_path, target_function, manual_curator, suggestions_file
                    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target_function", help="The function to search for")
    parser.add_argument("--files", nargs="+", help="The files to search in", default=[])
    (
        parser.add_argument(
            "--dirs",
            nargs="+",
            help="The directories to search in, recursively",
            default=[],
        ),
    )
    parser.add_argument(
        "--manual_curation",
        default="manual_curation.csv",
        help="The file containing manual curation data",
    )
    parser.add_argument(
        "--logging_level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    parser.add_argument(
        "--suggestions_file",
        default=None,
        help="File to write suggestions for more manual curations to",
    )

    args = parser.parse_args()

    # Setup logger
    logger.setLevel(args.logging_level)
    handler = logging.StreamHandler()
    handler.setLevel(args.logging_level)
    logger.addHandler(handler)

    main(
        args.target_function,
        args.files,
        args.dirs,
        args.manual_curation,
        args.suggestions_file,
    )
