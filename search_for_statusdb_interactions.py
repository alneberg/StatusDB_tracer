import ast
import argparse
import os


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
            f"Function {self.object}.{self.object}({self.argument}) called with keyword argument {self.keyword_arguments} within {self.class_scope}:{self.function_scope} in {self.file_name}:{self.line_number}"
        )


class FunctionCallVisitor(ast.NodeVisitor):
    def __init__(self, target_function, file_name):
        self.target_function = target_function
        self.function_calls = []
        self.file_name = file_name
        self.current_function = None
        self.current_class = None

    def visit_ClassDef(self, node):
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = None

    def visit_FunctionDef(self, node):
        self.current_function = node.name

        self.generic_visit(node)
        self.current_function = None

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

            if isinstance(node.func.value, ast.Name):
                object = f"<variable:{node.func.value.id}>"
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


def find_function_calls_in_files(target_function, files, dirs):
    for file_name in files:
        with open(file_name, "r") as f:
            source_code = f.read()
        tree = ast.parse(source_code)

        visitor = FunctionCallVisitor(target_function, file_name)
        visitor.visit(tree)
        for context in visitor.function_calls:
            context.print()
            print(
                f"Function {target_function}.{target_function}({context.argument}) called with keyword argument {context.keyword_arguments} within {context.function_scope} in {context.file_name}:{context.line_number}"
            )
    # Recurse through directories
    for directory in dirs:
        for file_name in os.listdir(directory):
            if file_name.endswith(".py"):
                file_path = os.path.join(directory, file_name)
                with open(file_path, "r") as f:
                    source_code = f.read()
                tree = ast.parse(source_code)
                visitor = FunctionCallVisitor(target_function, file_path)
                visitor.visit(tree)
                for context in visitor.function_calls:
                    context.print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target_function", help="The function to search for")
    parser.add_argument("--files", nargs="+", help="The files to search in", default=[])
    parser.add_argument(
        "--dirs",
        nargs="+",
        help="The directories to search in, recursively",
        default=[],
    )
    args = parser.parse_args()
    find_function_calls_in_files(args.target_function, args.files, args.dirs)
