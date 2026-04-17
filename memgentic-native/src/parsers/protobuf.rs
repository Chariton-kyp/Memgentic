use pyo3::prelude::*;

/// Read a protobuf varint starting at `pos`.
/// Returns (decoded value, new position) or None on error.
fn read_varint(data: &[u8], mut pos: usize) -> Option<(u64, usize)> {
    let mut result: u64 = 0;
    let mut shift: u32 = 0;
    while pos < data.len() {
        let byte = data[pos];
        pos += 1;
        result |= ((byte & 0x7F) as u64) << shift;
        if byte & 0x80 == 0 {
            return Some((result, pos));
        }
        shift += 7;
        if shift > 63 {
            return None; // malformed
        }
    }
    None
}

/// Heuristic: return true if the text is mostly human-readable.
fn is_readable_text(text: &str) -> bool {
    if text.trim().is_empty() {
        return false;
    }
    let printable = text
        .chars()
        .filter(|c| c.is_alphanumeric() || c.is_whitespace() || c.is_ascii_punctuation())
        .count();
    let total = text.chars().count();
    if total == 0 {
        return false;
    }
    (printable as f64 / total as f64) >= 0.85
}

/// Extract UTF-8 strings from raw protobuf wire-format data.
///
/// Walks the wire format and pulls out all length-delimited fields
/// that decode as valid UTF-8 text. Non-string fields (nested messages)
/// are recursively parsed.
fn extract_strings_inner(data: &[u8], min_length: usize) -> Vec<String> {
    let mut strings = Vec::new();
    let mut pos = 0;
    let size = data.len();

    while pos < size {
        // Read varint (field tag)
        let (tag, new_pos) = match read_varint(data, pos) {
            Some(v) => v,
            None => break,
        };
        pos = new_pos;
        if pos >= size {
            break;
        }

        let wire_type = tag & 0x07;

        match wire_type {
            0 => {
                // Varint — skip
                match read_varint(data, pos) {
                    Some((_, new_pos)) => pos = new_pos,
                    None => break,
                }
            }
            1 => {
                // 64-bit fixed — skip 8 bytes
                pos += 8;
            }
            2 => {
                // Length-delimited (string, bytes, nested message, packed repeated)
                let (length, new_pos) = match read_varint(data, pos) {
                    Some(v) => v,
                    None => break,
                };
                pos = new_pos;
                let length = length as usize;
                if pos + length > size {
                    break;
                }
                let chunk = &data[pos..pos + length];
                pos += length;

                // Try to decode as UTF-8 text
                match std::str::from_utf8(chunk) {
                    Ok(text) if text.len() >= min_length && is_readable_text(text) => {
                        strings.push(text.to_string());
                    }
                    _ => {
                        // Not a string — try recursing as nested message
                        let nested = extract_strings_inner(chunk, min_length);
                        strings.extend(nested);
                    }
                }
            }
            5 => {
                // 32-bit fixed — skip 4 bytes
                pos += 4;
            }
            _ => {
                // Unknown wire type — cannot continue safely
                break;
            }
        }
    }

    strings
}

/// Fallback text extraction — scan for runs of printable UTF-8.
fn extract_strings_fallback_inner(data: &[u8], min_length: usize) -> Vec<String> {
    let mut strings = Vec::new();
    let mut pos = 0;
    let size = data.len();

    while pos < size {
        // Skip non-printable bytes
        if !(data[pos] >= 32 && data[pos] <= 126)
            && data[pos] != 9
            && data[pos] != 10
            && data[pos] != 13
        {
            pos += 1;
            continue;
        }

        // Start of a potential text run
        let start = pos;
        while pos < size
            && ((data[pos] >= 32 && data[pos] <= 126)
                || data[pos] == 9
                || data[pos] == 10
                || data[pos] == 13)
        {
            pos += 1;
        }

        let chunk = &data[start..pos];
        if let Ok(text) = std::str::from_utf8(chunk) {
            let trimmed = text.trim();
            if trimmed.len() >= min_length && is_readable_text(trimmed) {
                strings.push(trimmed.to_string());
            }
        }
    }

    strings
}

/// Extract UTF-8 strings from raw protobuf wire-format data.
///
/// Walks the wire format and pulls out all length-delimited fields
/// that decode as valid UTF-8 text. Returns ordered list of extracted strings.
#[pyfunction]
#[pyo3(signature = (data, min_length=10))]
pub fn extract_strings_from_protobuf(data: &[u8], min_length: usize) -> Vec<String> {
    extract_strings_inner(data, min_length)
}

/// Fallback text extraction — scan for runs of printable UTF-8.
///
/// Used when structured protobuf parsing yields no results.
#[pyfunction]
#[pyo3(signature = (data, min_length=20))]
pub fn extract_strings_fallback(data: &[u8], min_length: usize) -> Vec<String> {
    extract_strings_fallback_inner(data, min_length)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_readable_text() {
        assert!(is_readable_text("Hello, this is readable text."));
        assert!(!is_readable_text(""));
        assert!(!is_readable_text("   "));
    }

    #[test]
    fn test_read_varint_simple() {
        let data = [0x0A]; // value 10
        let (value, pos) = read_varint(&data, 0).unwrap();
        assert_eq!(value, 10);
        assert_eq!(pos, 1);
    }

    #[test]
    fn test_read_varint_multibyte() {
        let data = [0xAC, 0x02]; // value 300
        let (value, pos) = read_varint(&data, 0).unwrap();
        assert_eq!(value, 300);
        assert_eq!(pos, 2);
    }

    #[test]
    fn test_extract_strings_fallback_finds_text() {
        let text =
            b"some binary \x00\x01\x02 Hello World this is text \x00\x00 more content here ok";
        let result = extract_strings_fallback_inner(text, 10);
        assert!(!result.is_empty());
    }

    #[test]
    fn test_extract_empty_data() {
        let result = extract_strings_inner(&[], 10);
        assert!(result.is_empty());
    }
}
