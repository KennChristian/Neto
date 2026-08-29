# Zod Schema Examples

## Example: User New Form Schema

Based on the actual `user-new.schema.ts` and `user-new.schema.test.ts` patterns in this codebase.

### Schema (`user-new.schema.ts`)

```typescript
import { z } from "zod";

/**
 * User New Form Validation Schema
 *
 * Validates all fields for creating a new user including:
 * - Personal information (name, DOB, sex)
 * - Account credentials (email, password)
 * - Role and organization assignment
 */
export const userNewFormSchema = z
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
      .regex(
        /^[a-zA-Z\s\-'.]*$/,
        "Middle name can only contain letters, spaces, hyphens, apostrophes, and periods"
      )
      .optional()
      .or(z.literal("")),
    lastName: z
      .string()
      .min(1, "Last name is required")
      .max(100, "Last name must not exceed 100 characters")
      .regex(
        /^[a-zA-Z\s\-'.]+$/,
        "Last name can only contain letters, spaces, hyphens, apostrophes, and periods"
      ),
    dateOfBirth: z
      .string()
      .min(1, "Date of birth is required")
      .refine((date) => new Date(date) < new Date(), {
        message: "Date of birth must be in the past",
      })
      .refine(
        (date) => {
          const age = new Date().getFullYear() - new Date(date).getFullYear();
          return age >= 18 && age <= 100;
        },
        { message: "User must be between 18 and 100 years old" }
      ),
    sex: z.enum(["Male", "Female"], {
      errorMap: () => ({ message: "Please select a sex" }),
    }),

    // Account Information
    email: z
      .string()
      .min(1, "Email address is required")
      .email("Please enter a valid email address")
      .max(255, "Email address must not exceed 255 characters")
      .toLowerCase(),
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .max(128, "Password must not exceed 128 characters")
      .regex(
        /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/,
        "Password must contain at least one uppercase letter, one lowercase letter, and one number"
      ),
    confirmPassword: z.string().min(1, "Please confirm your password"),

    // Role & Hospital
    role: z.enum(
      ["Admin", "Editor", "Viewer"],
      { errorMap: () => ({ message: "Please select a role" }) }
    ),
    organizationCode: z.string().min(1, "Organization code is required"),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

export type UserNewFormData = z.infer<typeof userNewFormSchema>;
```

### Test (`user-new.schema.test.ts`)

```typescript
import { describe, it } from "vitest";

import {
  expectSchemaInvalid,
  expectSchemaValid,
} from "@/test/helpers/schema-test-utils";

import { userNewFormSchema } from "./user-new.schema";

function validUserData() {
  return {
    firstName: "Juan",
    middleName: "Santos",
    lastName: "Dela Cruz",
    dateOfBirth: "1990-05-15",
    sex: "Male" as const,
    email: "juan@example.com",
    password: "Password1",
    confirmPassword: "Password1",
    role: "Admin" as const,
    organizationCode: "001",
  };
}

describe("userNewFormSchema", () => {
  // Happy path
  it("should accept valid user data", () => {
    expectSchemaValid(userNewFormSchema, validUserData());
  });

  // ──── Name validation ────
  it("should reject empty firstName", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), firstName: "" },
      "firstName"
    );
  });

  it("should reject firstName with numbers", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), firstName: "Juan123" },
      "firstName"
    );
  });

  it("should allow empty middleName", () => {
    expectSchemaValid(userNewFormSchema, {
      ...validUserData(),
      middleName: "",
    });
  });

  it("should allow undefined middleName", () => {
    const data = validUserData();
    delete (data as Record<string, unknown>).middleName;
    expectSchemaValid(userNewFormSchema, data);
  });

  it("should reject firstName over 100 characters", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), firstName: "A".repeat(101) },
      "firstName"
    );
  });

  // ──── Email validation ────
  it("should reject invalid email", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), email: "not-email" },
      "email"
    );
  });

  it("should reject empty email", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), email: "" },
      "email"
    );
  });

  // ──── Password validation ────
  it("should reject password shorter than 8 chars", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), password: "Pw1", confirmPassword: "Pw1" },
      "password"
    );
  });

  it("should reject password over 128 characters", () => {
    const longPass = "Aa1" + "x".repeat(126);
    expectSchemaInvalid(
      userNewFormSchema,
      {
        ...validUserData(),
        password: longPass,
        confirmPassword: longPass,
      },
      "password"
    );
  });

  // ──── Cross-field: password confirmation ────
  it("should reject mismatched passwords", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), confirmPassword: "Different1" },
      "confirmPassword",
      "do not match"
    );
  });

  // ──── Date of birth ────
  it("should reject future date of birth", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), dateOfBirth: "2099-01-01" },
      "dateOfBirth"
    );
  });

  it("should reject under 18 years old", () => {
    const today = new Date();
    const tooYoung = new Date(
      today.getFullYear() - 15,
      today.getMonth(),
      today.getDate()
    )
      .toISOString()
      .split("T")[0];
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), dateOfBirth: tooYoung },
      "dateOfBirth"
    );
  });

  // ──── Enum validation ────
  it("should reject invalid role", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), role: "Invalid Role" },
      "role"
    );
  });

  it("should reject invalid sex value", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), sex: "Other" },
      "sex"
    );
  });

  // ──── Organization code ────
  it("should reject empty organization code", () => {
    expectSchemaInvalid(
      userNewFormSchema,
      { ...validUserData(), organizationCode: "" },
      "organizationCode"
    );
  });

  it("should accept any non-empty organization code", () => {
    expectSchemaValid(userNewFormSchema, {
      ...validUserData(),
      organizationCode: "042",
    });
  });
});
```

**Key patterns demonstrated:**

- **`validData()` factory**: Baseline valid data, override per test with spread
- **`expectSchemaValid`**: Asserts data passes — clear error output on failure
- **`expectSchemaInvalid(schema, data, path, message)`**: Pinpoint error path and message
- **`as const`** for enum literal values in test data
- **No `expect` import**: Schema helpers handle assertions internally
- **Cross-field refinement test**: Uses `path` and `message` arguments
- **Boundary tests**: Min length, max length, regex, age range
