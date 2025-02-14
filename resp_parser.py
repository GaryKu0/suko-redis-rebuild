class RESPParser:
    '''
    len(parsed) = how many args
    parsed[0] = command
    parsed[1] = first arg
    ... etc
    '''
    def __init__(self, data: str):
        self.data = data
        self.lines = data.split("\r\n")
        if self.lines and self.lines[-1] == "":
            self.lines.pop()
    def parse(self):
        if not self.lines:
            return []
        if self.lines[0].startswith("*"):
            try:
                num_elements = int(self.lines[0][1:])
            except ValueError:
                return []
            elements = []
            i = 1
            for _ in range(num_elements):
                if i >= len(self.lines):
                    break
                if self.lines[i].startswith("$"):
                    i += 1
                    if i < len(self.lines):
                        elements.append(self.lines[i])
                        i += 1
                    else:
                        elements.append("")
                else:
                    elements.append(self.lines[i])
                    i += 1
            return elements
        else:
            return self.lines
