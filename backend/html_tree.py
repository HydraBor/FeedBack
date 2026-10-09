"""Small HTML reader for server-rendered OJ pages; never executes scripts."""
from html.parser import HTMLParser

class Node:
    def __init__(self, tag="", attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs or []), parent
        self.children = []

    def text(self):
        if self.tag in ("script", "style"):
            return ""
        return "".join(c.text() if isinstance(c, Node) else c for c in self.children)

    def all(self, tag=None, **attrs):
        found = []
        for child in self.children:
            if isinstance(child, Node):
                if (not tag or child.tag == tag) and all(child.attrs.get(k)==v for k,v in attrs.items()):
                    found.append(child)
                found.extend(child.all(tag, **attrs))
        return found

    def first(self, tag=None, **attrs):
        return next(iter(self.all(tag, **attrs)), None)

class Reader(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.current = self.root
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in ("input","br","hr","img","meta","link","source","wbr","area","base","embed","param","col"):
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, value):
        self.current.children.append(value)

def parse(text):
    return Reader(text).root
