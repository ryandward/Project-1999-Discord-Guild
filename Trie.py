class Trie:
    ...
    def contains(self, key):
        node = self.root
        for char in key:
            if char in node.children:
                node = node.children[char]
            else:
                return False
        return node.is_end_of_word
    class Node:
        def __init__(self):
            self.children = {}
            self.is_end_of_word = False
            self.choices = []

    def __init__(self):
        self.root = self.Node()

    def insert(self, word, choice):
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = self.Node()
            node = node.children[char]
        node.is_end_of_word = True
        node.choices.append(choice)

    def search(self, prefix):
        node = self.root
        for char in prefix:
            if char not in node.children:
                return []
            node = node.children[char]
        return self._traverse(node)

    def _traverse(self, node):
        results = []
        if node.is_end_of_word:
            results.extend(node.choices)
        for child in node.children.values():
            results.extend(self._traverse(child))
        return results