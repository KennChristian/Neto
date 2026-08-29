---
name: zod-schema
description: Create Zod validation schemas for forms with colocated tests. Use when creating form validation, schema definitions, or when user says "create schema", "validation schema", "form validation", "Zod".
model: sonnet
---

# Zod Schema Generator

## When to Use

Use this skill when the user:

- Needs to create a Zod validation schema for a form
- Wants to add field validation rules
- Asks about form validation, cross-field validation, or Zod patterns
- Mentions keywords like "schema", "validation", "Zod", "form rules"

## Instructions

### 1. Gather Requirements

Ask the user for:

- **Entity/form name**: What is being validated? (e.g., new user form, patient form)
- **Fields**: What fields need validation?
- **Rules**: What validation rules per field? (required, min/max, regex, enum)
- **Cross-field**: Any cross-field validations? (password confirmation, date ranges)

### 2. File Structure

```
src/lib/validations/
├── {entity}.schema.ts          # Schema + inferred type
├── {entity}.schema.test.ts     # Colocated test
```

### 3. Schema Template

```typescript
import { z } from "zod";

/**
 * Entity Form Validation Schema
 *
 * Validates fields for [description of what this validates].
 */
export const entityFormSchema = z
  .object({
    // Personal Information
    firstName: z
      .string()
      .min(1, "First name is required")
      .max(100, "First name must not exceed 100 characters")
      .regex(
        /^[a-zA-Z\s\-'.]+$/,
        "First name can only contain letters, spaces, hyphens, apostrophes, and periods"
      ),
    middleName: z
      .string()
      .max(100, "Middle name must not exceed 100 characters")
      .optional()
      .or(z.literal("")),

    // Account Information
    email: z
      .string()
      .min(1, "Email is required")
      .email("Please enter a valid email address")
      .max(255, "Email must not exceed 255 characters")
      .toLowerCase(),

    // Enum fields
    role: z.enum(
      ["Admin", "Editor", "Viewer"],
      { errorMap: () => ({ message: "Please select a role" }) }
    ),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

export type EntityFormData = z.infer<typeof entityFormSchema>;
```

### 4. Common Validation Patterns

#### Required String

```typescript
firstName: z.string().min(1, "First name is required");
```

#### Name with Regex

```typescript
firstName: z.string()
  .min(1, "First name is required")
  .max(100, "Must not exceed 100 characters")
  .regex(
    /^[a-zA-Z\s\-'.]+$/,
    "Can only contain letters, spaces, hyphens, apostrophes"
  );
```

#### Optional String (empty allowed)

```typescript
middleName: z.string()
  .max(100, "Must not exceed 100 characters")
  .optional()
  .or(z.literal(""));
```

#### Email

```typescript
email: z.string()
  .min(1, "Email is required")
  .email("Please enter a valid email address")
  .max(255, "Must not exceed 255 characters")
  .toLowerCase();
```

#### Password

```typescript
password: z.string()
  .min(8, "Password must be at least 8 characters")
  .max(128, "Password must not exceed 128 characters")
  .regex(
    /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/,
    "Must contain uppercase, lowercase, and number"
  );
```

#### Date of Birth (with age validation)

```typescript
dateOfBirth: z.string()
  .min(1, "Date of birth is required")
  .refine((date) => new Date(date) < new Date(), {
    message: "Date of birth must be in the past",
  })
  .refine(
    (date) => {
      const age = new Date().getFullYear() - new Date(date).getFullYear();
      return age >= 18 && age <= 100;
    },
    { message: "Must be between 18 and 100 years old" }
  );
```

#### Enum

```typescript
sex: z.enum(["Male", "Female"], {
  errorMap: () => ({ message: "Please select a sex" }),
});
```

#### Cross-field Refinement (password confirmation)

```typescript
.refine((data) => data.password === data.confirmPassword, {
  message: "Passwords do not match",
  path: ["confirmPassword"],  // Maps error to specific field
})
```

### 5. Type Export

Always export the inferred type alongside the schema:

```typescript
export const entityFormSchema = z.object({
  /* ... */
});
export type EntityFormData = z.infer<typeof entityFormSchema>;
```

### 6. Testing with Schema Helpers

Use `expectSchemaValid`/`expectSchemaInvalid` from `@/test/helpers/schema-test-utils`:

```typescript
import { describe, it } from "vitest";

import {
  expectSchemaInvalid,
  expectSchemaValid,
} from "@/test/helpers/schema-test-utils";

import { entityFormSchema } from "./entity.schema";

function validData() {
  return {
    firstName: "Juan",
    middleName: "Santos",
    lastName: "Dela Cruz",
    email: "juan@example.com",
    // ... all required fields with valid values
  };
}

describe("entityFormSchema", () => {
  it("should accept valid data", () => {
    expectSchemaValid(entityFormSchema, validData());
  });

  it("should reject empty firstName", () => {
    expectSchemaInvalid(
      entityFormSchema,
      { ...validData(), firstName: "" },
      "firstName"
    );
  });

  it("should reject invalid email", () => {
    expectSchemaInvalid(
      entityFormSchema,
      { ...validData(), email: "not-email" },
      "email"
    );
  });

  // Cross-field refinement
  it("should reject mismatched passwords", () => {
    expectSchemaInvalid(
      entityFormSchema,
      { ...validData(), confirmPassword: "Different1" },
      "confirmPassword",
      "do not match"
    );
  });
});
```

### 7. Conventions

- Use `type` not `interface` (the inferred type is already a `type`)
- Schema file name: `{entity}.schema.ts`
- Export both schema and inferred type
- Use descriptive error messages
- `as const` for enum literal values in test data
- `@/` path alias for imports

### 8. Checklist

- [ ] Schema exported as named export
- [ ] Type exported via `z.infer<typeof schema>`
- [ ] All required fields have `.min(1, "... is required")` validation
- [ ] String lengths have `.max()` bounds
- [ ] Email uses `.email()` and `.toLowerCase()`
- [ ] Enum fields use `z.enum()` with `errorMap`
- [ ] Cross-field validations use `.refine()` with `path`
- [ ] Test file uses `expectSchemaValid`/`expectSchemaInvalid`
- [ ] Test has `validData()` factory function
- [ ] Each validation rule has at least one test

## References

For detailed patterns, see [REFERENCE.md](REFERENCE.md).
For examples, see [EXAMPLES.md](EXAMPLES.md).
