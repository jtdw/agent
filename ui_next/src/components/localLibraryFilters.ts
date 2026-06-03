import type { LocalLibraryItem } from '@/lib/api';

const hiddenDocPatterns = [
  /^readme(?:[_-].*)?\.(?:md|txt)$/i,
  /^license(?:[_-].*)?\.(?:md|txt)$/i,
  /_from_source\.(?:md|txt)$/i
];

export function isUserVisibleLibraryItem(item: Pick<LocalLibraryItem, 'name' | 'path' | 'data_type'>) {
  const name = String(item.name || '').split(/[\\/]/).pop() || '';
  const pathName = String(item.path || '').split(/[\\/]/).pop() || '';
  if (item.data_type !== 'document') return true;
  return !hiddenDocPatterns.some((pattern) => pattern.test(name) || pattern.test(pathName));
}

export function filterUserVisibleLibraryItems(items: LocalLibraryItem[]) {
  return items.filter(isUserVisibleLibraryItem);
}
