# Frontend Hook Examples

## Example: User Hooks

Demonstrates TanStack Query hook patterns with query keys, queries, and mutations.

### Hook (`useUsers.ts`)

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { userService } from "@/services/user.service";

import type {
  EditUserFormData,
  NewUserFormData,
  UserQueryParams,
} from "@/types/user.types";

// ============================================
// QUERY KEYS
// ============================================

export const userKeys = {
  all: ["users"] as const,
  lists: () => [...userKeys.all, "list"] as const,
  list: (params: UserQueryParams) => [...userKeys.lists(), params] as const,
  details: () => [...userKeys.all, "detail"] as const,
  detail: (id: string | number) => [...userKeys.details(), id] as const,
  checkEmail: (email: string) =>
    [...userKeys.all, "check-email", email] as const,
};

// ============================================
// QUERIES
// ============================================

export const useUsers = (params: UserQueryParams = {}) => {
  return useQuery({
    queryKey: userKeys.list(params),
    queryFn: () => userService.getUsers(params),
    staleTime: 30000,
    gcTime: 300000,
  });
};

export const useUser = (userId: string | number) => {
  return useQuery({
    queryKey: userKeys.detail(userId),
    queryFn: () => userService.getUser(userId),
    enabled: !!userId,
    staleTime: 30000,
    gcTime: 300000,
  });
};

export const useCheckEmail = (email: string, isEnabled = false) => {
  return useQuery({
    queryKey: userKeys.checkEmail(email),
    queryFn: () => userService.checkEmailAvailability(email),
    enabled: isEnabled && !!email && email.includes("@"),
    staleTime: 60000,
    retry: false,
  });
};

// ============================================
// MUTATIONS
// ============================================

export const useCreateUser = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: NewUserFormData) => userService.createUser(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: userKeys.lists() });
    },
  });
};

export const useUpdateUser = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string | number;
      data: EditUserFormData;
    }) => userService.updateUser(id, data),
    onSuccess: (updatedUser) => {
      void queryClient.invalidateQueries({ queryKey: userKeys.lists() });
      queryClient.setQueryData(
        userKeys.detail(updatedUser.userId),
        updatedUser
      );
    },
  });
};
```

### Test (`useUsers.test.tsx`)

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useCheckEmail,
  useCreateUser,
  userKeys,
  useUser,
  useUsers,
} from "./useUsers";

import type { UserManagement } from "@/types/user.types";
import type { ReactNode } from "react";

// ============================================================================
// Mocks
// ============================================================================

vi.mock("@/services/user.service", () => ({
  userService: {
    getUsers: vi.fn(),
    getUser: vi.fn(),
    createUser: vi.fn(),
    checkEmailAvailability: vi.fn(),
  },
}));

import { userService } from "@/services/user.service";

const mockGetUsers = vi.mocked(userService.getUsers);
const mockGetUser = vi.mocked(userService.getUser);
const mockCreateUser = vi.mocked(userService.createUser);
const mockCheckEmail = vi.mocked(userService.checkEmailAvailability);

// ============================================================================
// Helper
// ============================================================================

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });

  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

const mockUser: UserManagement = {
  id: 1,
  userId: 1,
  firstName: "Juan",
  middleName: null,
  lastName: "Dela Cruz",
  dateOfBirth: "1990-05-15",
  sex: "Male",
  email: "juan@example.com",
  role: "Editor",
  status: "Active",
  isActive: true,
  isVerified: true,
  createdAt: "2024-01-01T00:00:00Z",
  updatedAt: "2024-01-15T10:00:00Z",
  lastLoginAt: null,
};

// ============================================================================
// Tests
// ============================================================================

describe("useUsers hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ==========================================================================
  // Query key factory
  // ==========================================================================
  describe("userKeys", () => {
    it("should generate correct all key", () => {
      expect(userKeys.all).toEqual(["users"]);
    });

    it("should generate correct list key with params", () => {
      expect(userKeys.list({ page: 1, limit: 10 })).toEqual([
        "users",
        "list",
        { page: 1, limit: 10 },
      ]);
    });

    it("should generate correct detail key", () => {
      expect(userKeys.detail(42)).toEqual(["users", "detail", 42]);
    });
  });

  // ==========================================================================
  // useUsers
  // ==========================================================================
  describe("useUsers", () => {
    it("should fetch users", async () => {
      mockGetUsers.mockResolvedValue({
        data: [],
        meta: {
          page: 1,
          limit: 10,
          total: 0,
          totalPages: 0,
          hasNext: false,
          hasPrev: false,
        },
      });

      const { result } = renderHook(() => useUsers(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data?.data).toEqual([]);
    });
  });

  // ==========================================================================
  // useUser
  // ==========================================================================
  describe("useUser", () => {
    it("should fetch a single user", async () => {
      mockGetUser.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useUser(1), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data?.firstName).toBe("Juan");
    });

    it("should not fetch when userId is empty string", () => {
      const { result } = renderHook(() => useUser(""), {
        wrapper: createWrapper(),
      });

      expect(result.current.isFetching).toBe(false);
      expect(mockGetUser).not.toHaveBeenCalled();
    });
  });

  // ==========================================================================
  // useCheckEmail
  // ==========================================================================
  describe("useCheckEmail", () => {
    it("should check email when enabled and valid", async () => {
      mockCheckEmail.mockResolvedValue(true);

      const { result } = renderHook(
        () => useCheckEmail("test@example.com", true),
        { wrapper: createWrapper() }
      );

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toBe(true);
    });

    it("should not check when disabled", () => {
      const { result } = renderHook(
        () => useCheckEmail("test@example.com", false),
        { wrapper: createWrapper() }
      );

      expect(result.current.isFetching).toBe(false);
      expect(mockCheckEmail).not.toHaveBeenCalled();
    });
  });

  // ==========================================================================
  // useCreateUser
  // ==========================================================================
  describe("useCreateUser", () => {
    it("should create a user", async () => {
      mockCreateUser.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useCreateUser(), {
        wrapper: createWrapper(),
      });

      result.current.mutate({
        firstName: "Juan",
        lastName: "Dela Cruz",
        dateOfBirth: "1990-05-15",
        sex: "Male",
        email: "juan@example.com",
        password: "Password1!",
        confirmPassword: "Password1!",
        role: "Editor",
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockCreateUser).toHaveBeenCalled();
    });
  });
});
```

**Key patterns demonstrated:**

- `createWrapper()` with fresh `QueryClient` per test
- Mock service layer (not API layer)
- `renderHook` + `wrapper` option
- `waitFor` for async query assertions
- `enabled: false` test (assert `isFetching` is false)
- Query key factory tests as separate describe block
