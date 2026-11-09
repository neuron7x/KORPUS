from __future__ import annotations

import ast


class _DirectCalls(ast.NodeVisitor):
    """Skip nested function bodies until the target itself is reached."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []
        self.bindings: set[str] = set()
        self.definition_failures: list[str] = []

    def _check_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        a = node.args
        args = (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg)
        vals = (*a.defaults, *a.kw_defaults, node.returns)
        vals += tuple(x.annotation for x in args if x)
        if node.decorator_list or any(
            x is not None and not isinstance(x, (ast.Constant, ast.Name)) for x in vals
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
        if not isinstance(node.body, (ast.Constant, ast.Name)):
            self.definition_failures.append("lambda has unverified executable callback body")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.definition_failures.append("class definition has unverified execution")

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bindings.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        root = node.value
        while isinstance(root, (ast.Attribute, ast.Subscript)):
            root = root.value
        if isinstance(node.ctx, (ast.Store, ast.Del)) and isinstance(root, ast.Name):
            self.bindings.add(root.id)
        self.generic_visit(node)
