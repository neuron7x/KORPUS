"""Definition-time AST safety checks for future migration admission."""

from __future__ import annotations

import ast


class _DirectCalls(ast.NodeVisitor):
    """Skip nested function bodies until the target itself is reached."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []
        self.bindings: set[str] = set()
        self.definition_failures: list[str] = []

    def _check_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        arguments = node.args
        annotations = [
            arg.annotation
            for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        ]
        if arguments.vararg is not None:
            annotations.append(arguments.vararg.annotation)
        if arguments.kwarg is not None:
            annotations.append(arguments.kwarg.annotation)
        evaluated = [*arguments.defaults, *arguments.kw_defaults, node.returns, *annotations]
        if node.decorator_list or any(
            expr is not None and not isinstance(expr, (ast.Constant, ast.Name))
            for expr in evaluated
        ):
            self.definition_failures.append(
                f"function {node.name} has unverified definition-time expressions"
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_signature(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_signature(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        if any(
            expr is not None and not isinstance(expr, ast.Constant)
            for expr in (*node.args.defaults, *node.args.kw_defaults)
        ):
            self.definition_failures.append("lambda has unverified definition-time expressions")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.definition_failures.append("class definition has unverified execution")

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.bindings.add(node.id)
