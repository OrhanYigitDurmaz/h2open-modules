#!/usr/bin/env python3
"""Flag server-only helpers in XML values that the web client evaluates.

Odoo stores the text of fields like an action's ``context`` or ``domain`` as
a plain string, and the browser evaluates it later with its own small Python
interpreter. That interpreter knows ``uid``, ``context_today``,
``relativedelta`` and friends, but not ``ref()`` or ``Command``, which only
exist while the server loads the XML file. Using them there crashes the
client with "Name 'ref' is not defined".

Two ways to write it correctly:

* evaluate on the server while loading:
  ``<field name="context" eval="{'default_categ_id': ref('module.xmlid')}"/>``
* substitute the database id into the string:
  ``<field name="context">{'default_categ_id': %(module.xmlid)d}</field>``

Checked: the text of every ``<field>`` without ``eval``/``ref``/``search``
(except Python code fields), and every attribute except ``eval``/``search``
(view arch attributes such as ``context``, ``domain``, ``invisible``).
"""

import re
import sys

from lxml import etree

# `ref(` not preceded by a name character or a dot, so `env.ref(` and
# `self.ref(` in server-side code stay allowed.
SERVER_ONLY = re.compile(r"(?<![\w.])(ref\(|Command\.)")
SERVER_EVAL_ATTRS = {"eval", "search", "ref"}
# Fields whose text is Python run on the server, where `env.ref` is fine.
CODE_FIELDS = {"code"}


def check_file(path):
    try:
        tree = etree.parse(path)
    except etree.XMLSyntaxError as exc:
        return [f"{path}:{exc.lineno or 0}: invalid XML: {exc.msg}"]
    errors = []
    for node in tree.iter(etree.Element):
        for attr, value in node.attrib.items():
            if attr in SERVER_EVAL_ATTRS:
                continue
            match = SERVER_ONLY.search(value)
            if match:
                errors.append(
                    f"{path}:{node.sourceline}: `{match.group(1)}` in attribute "
                    f"`{attr}` of <{node.tag}> is evaluated by the web client, "
                    "where it does not exist"
                )
        if (
            node.tag == "field"
            and node.text
            and not SERVER_EVAL_ATTRS & set(node.attrib)
            and node.get("name") not in CODE_FIELDS
        ):
            match = SERVER_ONLY.search(node.text)
            if match:
                errors.append(
                    f"{path}:{node.sourceline}: `{match.group(1)}` in the text of "
                    f"field `{node.get('name')}` is stored as a string and "
                    "evaluated by the web client, where it does not exist; use "
                    "`eval=\"...\"` or `%(module.xmlid)d`"
                )
    return errors


def main(paths):
    errors = [error for path in paths for error in check_file(path)]
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
