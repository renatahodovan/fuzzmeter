// Copyright (c) 2026 Renata Hodovan, Akos Kiss.
//
// Licensed under the BSD 3-Clause License
// <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
// This file may not be copied, modified, or distributed except
// according to those terms.

#ifndef GRAMMARINATOR_EXAMPLES_FUZZER_JAVASCRIPTSERIALIZER_HPP
#define GRAMMARINATOR_EXAMPLES_FUZZER_JAVASCRIPTSERIALIZER_HPP

#include "grammarinator/runtime/Rule.hpp"

#include <string>
#include <unordered_set>

using namespace grammarinator;
using namespace grammarinator::runtime;

inline std::string JavaScriptSerializer(const Rule* root) {
    std::string src;

    const std::unordered_set<std::string> ws_after_tokens = {
        "Async", "Await", "Break", "Case", "Catch", "Class", "Const", "Continue",
        "Debugger", "Default", "Delete", "Do", "Else", "Enum", "Export", "Extends",
        "Finally", "For", "Function_", "If", "Implements", "Import", "Interface",
        "StrictLet", "NonStrictLet", "Package", "Private", "Protected", "Public",
        "Return", "Super", "Switch", "Throw", "Try", "Typeof", "Var", "Void",
        "While", "With", "Yield", "YieldStar"
    };

    const std::unordered_set<std::string> ws_before_after_tokens = {
        "And", "ARROW", "As", "Extends", "From", "GreaterThanEquals", "IdentityEquals",
        "IdentityNotEquals", "In", "Instanceof", "Of", "Static",
    };

    auto walk = [&](const auto& self, const Rule* node) -> void {
        if (auto* token = dynamic_cast<const UnlexerRule*>(node)) {
            const std::string& current_src = token->src;
            if (current_src.empty()) {
                return;
            }

            const std::string& name = token->name;
            bool ws_before_after = ws_before_after_tokens.contains(name) || current_src == "static";
            if (ws_before_after) {
                src += " ";
            }
            if (current_src != "<EOF>") {
                src += current_src;
            }
            if (ws_before_after) {
                src += " ";
            } else if ((!name.empty() && ws_after_tokens.contains(name)) || current_src == "get" || current_src == "set") {
                src += " ";
            } else if (name == "New" && token->parent && token->parent->name != "singleExpression_MetaExpression") {
                src += " ";
            } else if (name == "HashBangLine") {
                src += "\n";
            }
            return;
        }

        auto* parent = dynamic_cast<const ParentRule*>(node);
        if (!parent) {
            return;
        }
        for (auto* child : parent->children) {
            self(self, child);
        }
        if (node->name == "statement" || node->name == "classElement") {
            src += "\n";
        } else if (node->name == "eos" && parent->children.empty()) {
            src += "\n";
        }
    };

    walk(walk, root);
    return src;
}

#endif // GRAMMARINATOR_EXAMPLES_FUZZER_JAVASCRIPTSERIALIZER_HPP
