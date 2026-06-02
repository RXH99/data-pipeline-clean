def read_csv_lines(filepath):
    result = []
    with open(filepath, 'r') as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(',')
            result.append({
                'col1': parts[0],
                'col2': parts[1],
                'col3': parts[2],
            })
    return result
