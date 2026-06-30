import type { LocalLibraryItem } from '@/lib/api';

const hiddenDocPatterns = [
  /^readme(?:[_-].*)?\.(?:md|txt)$/i,
  /^license(?:[_-].*)?\.(?:md|txt)$/i,
  /_from_source\.(?:md|txt)$/i
];

type LocalLibraryFilterItem = Pick<LocalLibraryItem, 'name' | 'filename' | 'data_type'> & { path?: string };

function basename(value: unknown) {
  return String(value || '').split(/[\\/]/).pop() || '';
}

export function isUserVisibleLibraryItem(item: LocalLibraryFilterItem) {
  const name = String(item.name || '').split(/[\\/]/).pop() || '';
  const filename = basename(item.filename);
  const pathName = basename(item.path);
  if (item.data_type !== 'document') return true;
  return !hiddenDocPatterns.some((pattern) => pattern.test(name) || pattern.test(filename) || pattern.test(pathName));
}

export function filterUserVisibleLibraryItems(items: LocalLibraryItem[]) {
  return items.filter(isUserVisibleLibraryItem);
}
