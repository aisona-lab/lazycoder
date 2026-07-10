import { useState } from "react";

interface SearchBoxProps {
  onSearch: (query: string) => void;
  debounceMs?: number;
}

export function SearchBox({ onSearch, debounceMs = 300 }: SearchBoxProps) {
  const [value, setValue] = useState("");
  const handleChange = (next: string) => {
    setValue(next);
    setTimeout(() => {
      onSearch(next);
    }, debounceMs);
  };
  return <input value={value} onChange={(e) => handleChange(e.target.value)} />;
}
