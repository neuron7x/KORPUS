// Reader-declared identity attributes. These are session context, never authentication.

export const DECLARATION_KEY = "korpus.declaration";

export const DECLARED_FIELDS = [
  {id: "family-name", key: "family_name", label: "Прізвище", min: 1},
  {id: "given-name", key: "given_name", label: "Ім’я", min: 1},
  {id: "specialty", key: "specialty", label: "Спеціальність", min: 2},
];

export function rememberDeclaration(declared) {
  try {
    sessionStorage.setItem(DECLARATION_KEY, JSON.stringify(declared));
  } catch {
    // Private mode or full quota: in-memory state in app.js still remains authoritative.
  }
  return declared;
}

export function forgetDeclaration() {
  try {
    sessionStorage.removeItem(DECLARATION_KEY);
  } catch {
    // Nothing to clean when storage is unavailable.
  }
}

export function restoreDeclaration() {
  try {
    const stored = sessionStorage.getItem(DECLARATION_KEY);
    if (!stored) return null;
    const parsed = JSON.parse(stored);
    // Re-validate browser storage: it is convenience state, never trusted input.
    if (["family_name", "given_name", "specialty"].every(
      key => typeof parsed?.[key] === "string" && parsed[key].trim(),
    )) {
      return parsed;
    }
  } catch {
    // Unparseable or unavailable storage is equivalent to no declaration.
  }
  return null;
}

export function readDeclaration(getElementById) {
  const problems = [];
  const declared = {};
  for (const field of DECLARED_FIELDS) {
    const element = getElementById(field.id);
    element.removeAttribute("aria-invalid");
    const value = element.value.trim();
    if (value.length < field.min) {
      problems.push({
        field: field.id,
        message: `${field.label}: ${value ? `щонайменше ${field.min} символи` : "заповніть поле"}`,
      });
      continue;
    }
    declared[field.key] = value;
  }
  return {declared, problems};
}
