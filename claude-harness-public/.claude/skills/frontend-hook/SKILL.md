---
name: frontend-hook
description: Create TanStack Query hooks for data fetching and mutations following project patterns. Use when creating query hooks, mutation hooks, custom hooks, or when user says "create hook", "useQuery", "useMutation", "custom hook".
model: sonnet
---

# Frontend Hook Generator

## When to Use

Use this skill when the user:

- Needs to create TanStack Query hooks for a new entity
- Wants to add data fetching or mutation hooks
- Asks about query keys, cache invalidation, or stale time
- Mentions keywords like "hook", "useQuery", "useMutation", "query key"

## Instructions

### 1. Gather Requirements

Ask the user for:

- **Entity name**: What resource? (e.g., patients, facilities)
- **Operations**: Which hooks are needed? (list, detail, create, update, delete)
- **Service layer**: Does a service already exist? (check the project's service layer)
- **Query parameters**: What filtering/pagination is needed?
- **Cache strategy**: Default stale/gc times or custom?

### 2. File Structure

```
src/hooks/
├── use{Entity}s.ts          # Query + mutation hooks
├── use{Entity}s.test.tsx    # Colocated test file
└── index.ts                 # Barrel export (add new export)
```

### 3. Hook File Structure

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { entityService } from "@/services/entity.service";

import type { EntityFormData, EntityQueryParams } from "@/types/entity.types";

// ============================================
// QUERY KEYS
// ============================================

export const entityKeys = {
  all: ["entities"] as const,
  lists: () => [...entityKeys.all, "list"] as const,
  list: (params: EntityQueryParams) => [...entityKeys.lists(), params] as const,
  details: () => [...entityKeys.all, "detail"] as const,
  detail: (id: string | number) => [...entityKeys.details(), id] as const,
};

// ============================================
// QUERIES
// ============================================

export const useEntities = (params: EntityQueryParams = {}) => {
  return useQuery({
    queryKey: entityKeys.list(params),
    queryFn: () => entityService.getEntities(params),
    staleTime: 30000, // 30 seconds
    gcTime: 300000, // 5 minutes
  });
};

export const useEntity = (id: string | number) => {
  return useQuery({
    queryKey: entityKeys.detail(id),
    queryFn: () => entityService.getEntity(id),
    enabled: !!id,
    staleTime: 30000,
    gcTime: 300000,
  });
};

// ============================================
// MUTATIONS
// ============================================

export const useCreateEntity = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: EntityFormData) => entityService.createEntity(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: entityKeys.lists() });
    },
  });
};

export const useUpdateEntity = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: EntityFormData }) =>
      entityService.updateEntity(id, data),
    onSuccess: (updatedEntity) => {
      void queryClient.invalidateQueries({ queryKey: entityKeys.lists() });
      queryClient.setQueryData(
        entityKeys.detail(updatedEntity.id),
        updatedEntity
      );
    },
  });
};
```

### 4. Query Key Factory Pattern

The key factory creates a hierarchical structure for targeted cache invalidation:

```
entityKeys.all            → ["entities"]                    // Invalidate everything
entityKeys.lists()        → ["entities", "list"]            // Invalidate all lists
entityKeys.list(params)   → ["entities", "list", {page,..}] // Specific list variant
entityKeys.details()      → ["entities", "detail"]          // Invalidate all details
entityKeys.detail(id)     → ["entities", "detail", 42]      // Specific entity
```

### 5. Common useQuery Options

| Option            | Usage                                                       | Default       |
| ----------------- | ----------------------------------------------------------- | ------------- |
| `queryKey`        | Cache key — hierarchical array                              | Required      |
| `queryFn`         | Async function returning data                               | Required      |
| `staleTime`       | Time before data is considered stale                        | `30000` (30s) |
| `gcTime`          | Time before unused cache is garbage collected               | `300000` (5m) |
| `enabled`         | Conditionally run query                                     | `true`        |
| `placeholderData` | Show while fetching (use `keepPreviousData` for pagination) | -             |
| `retry`           | Retry failed requests                                       | `3` (default) |

### 6. Common useMutation Options

| Option       | Usage                                        |
| ------------ | -------------------------------------------- |
| `mutationFn` | Async function to execute                    |
| `onSuccess`  | Invalidate queries, update cache, show toast |
| `onError`    | Show error toast                             |

### 7. Cache Invalidation Patterns

```typescript
// Invalidate all entity lists (any params)
void queryClient.invalidateQueries({ queryKey: entityKeys.lists() });

// Update a specific entity in cache (optimistic)
queryClient.setQueryData(entityKeys.detail(id), updatedEntity);

// Invalidate everything for this entity
void queryClient.invalidateQueries({ queryKey: entityKeys.all });
```

### 8. Testing Pattern

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { entityKeys, useEntities } from "./useEntities";

import type { ReactNode } from "react";

vi.mock("@/services/entity.service", () => ({
  entityService: { getEntities: vi.fn(), createEntity: vi.fn() },
}));

import { entityService } from "@/services/entity.service";

const mockGetEntities = vi.mocked(entityService.getEntities);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useEntities", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  describe("entityKeys", () => {
    it("should generate correct list key", () => {
      expect(entityKeys.list({ page: 1 })).toEqual(["entities", "list", { page: 1 }]);
    });
  });

  describe("useEntities", () => {
    it("should fetch entities", async () => {
      mockGetEntities.mockResolvedValue({ data: [], meta: { /* ... */ } });

      const { result } = renderHook(() => useEntities(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data?.data).toEqual([]);
    });
  });
});
```

### 9. Barrel Export

Add to the hooks barrel export (e.g., `hooks/index.ts`):

```typescript
export {
  entityKeys,
  useEntities,
  useEntity,
  useCreateEntity,
} from "./useEntities";
```

### 10. Conventions

- Use `type` not `interface`
- Use `import type { ... }` for type-only imports
- Named exports only (arrow functions)
- `@/` path alias for imports
- `void` prefix for fire-and-forget promises: `void queryClient.invalidateQueries()`
- Mock service layer (not API layer) in hook tests

### 11. Checklist

- [ ] Query key factory with `as const` tuples
- [ ] Section separators: QUERY KEYS, QUERIES, MUTATIONS
- [ ] `staleTime` and `gcTime` configured
- [ ] `enabled` guard for conditional queries (e.g., `enabled: !!id`)
- [ ] `void` prefix on `invalidateQueries` calls
- [ ] `setQueryData` for optimistic detail cache updates
- [ ] Test file with `createWrapper()` and mock-then-import
- [ ] Added to barrel export in `hooks/index.ts`

## References

For detailed patterns, see [REFERENCE.md](REFERENCE.md).
For examples, see [EXAMPLES.md](EXAMPLES.md).
