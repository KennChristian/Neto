# Frontend Hook Reference

## Query Key Factory Pattern

The query key factory creates hierarchical keys that enable targeted cache invalidation. Each level builds on the previous one using spread syntax.

```typescript
export const entityKeys = {
  all: ["entities"] as const,
  lists: () => [...entityKeys.all, "list"] as const,
  list: (params: EntityQueryParams) => [...entityKeys.lists(), params] as const,
  details: () => [...entityKeys.all, "detail"] as const,
  detail: (id: string | number) => [...entityKeys.details(), id] as const,
  // Add custom keys as needed:
  checkEmail: (email: string) =>
    [...entityKeys.all, "check-email", email] as const,
};
```

### Invalidation Hierarchy

```
invalidateQueries({ queryKey: entityKeys.all })
  ├── invalidates entityKeys.lists() and all list variants
  ├── invalidates entityKeys.details() and all detail variants
  └── invalidates any custom keys

invalidateQueries({ queryKey: entityKeys.lists() })
  └── invalidates ALL list variants regardless of params

invalidateQueries({ queryKey: entityKeys.detail(42) })
  └── invalidates ONLY the detail for id=42
```

## useQuery Options Reference

```typescript
export const useEntities = (params: EntityQueryParams = {}) => {
  return useQuery({
    // Required
    queryKey: entityKeys.list(params), // Cache key
    queryFn: () => entityService.getAll(params), // Data fetcher

    // Timing
    staleTime: 30000, // 30s — data considered fresh for this long
    gcTime: 300000, // 5m — unused cache kept for this long (formerly cacheTime)

    // Conditional
    enabled: !!params.id, // Only fetch when truthy

    // Pagination
    placeholderData: keepPreviousData, // Show old data while new page loads

    // Error handling
    retry: false, // Don't retry on error (useful for email checks)
  });
};
```

### Common staleTime/gcTime Values

| Use Case                          | staleTime    | gcTime       |
| --------------------------------- | ------------ | ------------ |
| User lists (changes infrequently) | 30000 (30s)  | 300000 (5m)  |
| Email availability check          | 60000 (1m)   | 300000 (5m)  |
| Static reference data             | 600000 (10m) | 3600000 (1h) |

## useMutation Options Reference

```typescript
export const useCreateEntity = () => {
  const queryClient = useQueryClient();

  return useMutation({
    // Required
    mutationFn: (data: EntityFormData) => entityService.create(data),

    // Success — invalidate related queries
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: entityKeys.lists() });
    },

    // Success with cache update — avoid refetch for detail
    onSuccess: (updatedEntity) => {
      void queryClient.invalidateQueries({ queryKey: entityKeys.lists() });
      queryClient.setQueryData(
        entityKeys.detail(updatedEntity.id),
        updatedEntity
      );
    },

    // Error handling (usually in component, not hook)
    // onError is rarely needed in the hook — handle in component's mutate call
  });
};
```

### Mutation with Compound Parameters

When mutations need both an ID and form data:

```typescript
export const useUpdateEntity = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string | number; data: EntityFormData }) =>
      entityService.update(id, data),
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

## Barrel Export Pattern

```typescript
// src/hooks/index.ts
export {
  entityKeys,
  useEntities,
  useEntity,
  useCreateEntity,
  useUpdateEntity,
  useDeleteEntity,
} from "./useEntities";
```

## Test Patterns

### createWrapper() for QueryClientProvider

Hook tests need a manual wrapper since `renderHook` doesn't use the custom `render` from test-utils:

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";

import type { ReactNode } from "react";

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
```

### Mock-then-import for Services

```typescript
// Mock the SERVICE layer (not the API layer)
vi.mock("@/services/entity.service", () => ({
  entityService: {
    getEntities: vi.fn(),
    getEntity: vi.fn(),
    createEntity: vi.fn(),
    updateEntity: vi.fn(),
  },
}));

import { entityService } from "@/services/entity.service";

const mockGetEntities = vi.mocked(entityService.getEntities);
const mockCreateEntity = vi.mocked(entityService.createEntity);
```

### Testing Query Hooks

```typescript
describe("useEntities", () => {
  it("should fetch entities", async () => {
    mockGetEntities.mockResolvedValue({
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

    const { result } = renderHook(() => useEntities(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.data).toEqual([]);
  });
});
```

### Testing Mutation Hooks

```typescript
describe("useCreateEntity", () => {
  it("should create an entity", async () => {
    mockCreateEntity.mockResolvedValue(mockEntity);

    const { result } = renderHook(() => useCreateEntity(), {
      wrapper: createWrapper(),
    });

    result.current.mutate(formData);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockCreateEntity).toHaveBeenCalled();
  });
});
```

### Testing Disabled Queries

```typescript
it("should not fetch when id is empty", () => {
  const { result } = renderHook(() => useEntity(""), {
    wrapper: createWrapper(),
  });

  expect(result.current.isFetching).toBe(false);
  expect(mockGetEntity).not.toHaveBeenCalled();
});
```

### Testing Query Key Factory

```typescript
describe("entityKeys", () => {
  it("should generate correct all key", () => {
    expect(entityKeys.all).toEqual(["entities"]);
  });

  it("should generate correct list key with params", () => {
    expect(entityKeys.list({ page: 1, limit: 10 })).toEqual([
      "entities",
      "list",
      { page: 1, limit: 10 },
    ]);
  });

  it("should generate correct detail key", () => {
    expect(entityKeys.detail(42)).toEqual(["entities", "detail", 42]);
  });
});
```
