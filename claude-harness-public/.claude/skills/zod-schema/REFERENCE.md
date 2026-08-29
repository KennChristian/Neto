# Zod Schema Reference


Schemas should be colocated in a validations directory (e.g., `src/lib/validations/`).

## Common Validators

### Name Fields

```typescript
// Required name
firstName: z
  .string()
  .min(1, "First name is required")
  .max(100, "First name must not exceed 100 characters")
  .regex(
    /^[a-zA-Z\s\-'.]+$/,
    "First name can only contain letters, spaces, hyphens, apostrophes, and periods"
  ),

// Optional name (empty string allowed)
middleName: z
  .string()
  .max(100, "Middle name must not exceed 100 characters")
  .regex(
    /^[a-zA-Z\s\-'.]*$/,   // Note: * not + (allows empty)
    "Middle name can only contain letters, spaces, hyphens, apostrophes, and periods"
  )
  .optional()
  .or(z.literal("")),
```

### Email

```typescript
email: z
  .string()
  .min(1, "Email address is required")
  .email("Please enter a valid email address")
  .max(255, "Email address must not exceed 255 characters")
  .toLowerCase(),
```

### Password

```typescript
password: z
  .string()
  .min(8, "Password must be at least 8 characters")
  .max(128, "Password must not exceed 128 characters")
  .regex(
    /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/,
    "Password must contain at least one uppercase letter, one lowercase letter, and one number"
  ),
confirmPassword: z.string().min(1, "Please confirm your password"),
```

### Date Fields

```typescript
// Required date
dateOfBirth: z
  .string()
  .min(1, "Date of birth is required")
  .refine(
    (date) => {
      const birthDate = new Date(date);
      const today = new Date();
      return birthDate < today;
    },
    { message: "Date of birth must be in the past" }
  )
  .refine(
    (date) => {
      const birthDate = new Date(date);
      const today = new Date();
      const age = today.getFullYear() - birthDate.getFullYear();
      return age >= 18 && age <= 100;
    },
    { message: "User must be between 18 and 100 years old" }
  ),
```

### Enum Fields

```typescript
sex: z.enum(["Male", "Female"], {
  errorMap: () => ({ message: "Please select a sex" }),
}),

role: z.enum(
  ["Admin", "Editor", "Viewer"],
  { errorMap: () => ({ message: "Please select a role" }) }
),

status: z.enum(["ACTIVE", "INACTIVE", "SUSPENDED"], {
  errorMap: () => ({ message: "Please select a status" }),
}),
```

### Required Codes

```typescript
organizationCode: z.string().min(1, "Organization code is required"),
```

## Refinement Patterns

### Cross-field Validation (Password Confirmation)

```typescript
export const schema = z
  .object({
    password: z.string().min(8, "..."),
    confirmPassword: z.string().min(1, "..."),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"], // Error appears on confirmPassword field
  });
```

### Date Range Validation

```typescript
export const schema = z
  .object({
    startDate: z.string().min(1, "Start date is required"),
    endDate: z.string().min(1, "End date is required"),
  })
  .refine((data) => new Date(data.endDate) > new Date(data.startDate), {
    message: "End date must be after start date",
    path: ["endDate"],
  });
```

## Type Export Pattern

Always export the inferred type alongside the schema:

```typescript
export const entityFormSchema = z.object({
  /* ... */
});
export type EntityFormData = z.infer<typeof entityFormSchema>;
```

This type is used in:

- React Hook Form: `useForm<EntityFormData>({ resolver: zodResolver(entityFormSchema) })`
- Service layer: `transformFormToApi(formData: EntityFormData)`
- Type definitions: `@/types/entity.types.ts`

## Schema Composition

### Intersection (extend base schema)

```typescript
const baseSchema = z.object({
  firstName: z.string().min(1),
  lastName: z.string().min(1),
});

const userSchema = z.intersection(
  baseSchema,
  z.object({
    email: z.string().email(),
    role: z.enum(["admin", "user"]),
  })
);
```

### Discriminated Union (different shapes by type)

```typescript
const notificationSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("email"),
    email: z.string().email(),
  }),
  z.object({
    type: z.literal("sms"),
    phone: z.string().min(10),
  }),
]);
```

## Test Helpers API

### `expectSchemaValid(schema, data)`

Asserts data passes validation. On failure, prints all issues with paths:

```
Expected schema to pass but got errors:
  [firstName] First name is required
  [email] Please enter a valid email address
```

### `expectSchemaInvalid(schema, data, path?, message?)`

Asserts data fails validation.

```typescript
// Just assert failure
expectSchemaInvalid(schema, invalidData);

// Assert failure at specific path
expectSchemaInvalid(schema, invalidData, "email");

// Assert failure at path with specific message
expectSchemaInvalid(schema, invalidData, "confirmPassword", "do not match");

// Assert failure with message (any path)
expectSchemaInvalid(schema, invalidData, undefined, "required");
```

Returns `ZodError` for additional assertions:

```typescript
const error = expectSchemaInvalid(schema, invalidData);
expect(error.issues).toHaveLength(2);
```

## Test Structure

```typescript
import { describe, it } from "vitest";

import {
  expectSchemaInvalid,
  expectSchemaValid,
} from "@/test/helpers/schema-test-utils";

import { entityFormSchema } from "./entity.schema";

// Factory returning baseline valid data
function validData() {
  return {
    firstName: "Juan",
    middleName: "Santos",
    lastName: "Dela Cruz",
    dateOfBirth: "1990-05-15",
    sex: "Male" as const, // Use as const for enum literals
    email: "juan@example.com",
    password: "Password1",
    confirmPassword: "Password1",
    role: "Admin" as const,
    organizationCode: "001",
  };
}

describe("entityFormSchema", () => {
  // Happy path
  it("should accept valid data", () => {
    expectSchemaValid(entityFormSchema, validData());
  });

  // Each field's validation rules
  it("should reject empty firstName", () => {
    expectSchemaInvalid(
      entityFormSchema,
      { ...validData(), firstName: "" },
      "firstName"
    );
  });

  it("should reject firstName with numbers", () => {
    expectSchemaInvalid(
      entityFormSchema,
      { ...validData(), firstName: "Juan123" },
      "firstName"
    );
  });

  // Optional field
  it("should allow empty middleName", () => {
    expectSchemaValid(entityFormSchema, { ...validData(), middleName: "" });
  });

  // Cross-field
  it("should reject mismatched passwords", () => {
    expectSchemaInvalid(
      entityFormSchema,
      { ...validData(), confirmPassword: "Different1" },
      "confirmPassword",
      "do not match"
    );
  });

  // Enum
  it("should reject invalid role", () => {
    expectSchemaInvalid(
      entityFormSchema,
      { ...validData(), role: "Invalid" },
      "role"
    );
  });
});
```
