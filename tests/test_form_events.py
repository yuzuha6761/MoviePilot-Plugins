"""用 Node 执行表单事件，不启动宿主、浏览器或访问外部服务。"""

import json
import shutil
import subprocess
import unittest

from helpers import load_plugin


@unittest.skipUnless(shutil.which("node"), "表单 JavaScript 交互验证需要 Node")
class FormEventTests(unittest.TestCase):
    def test_add_edit_switch_delete_and_round_trip(self):
        with load_plugin() as module:
            form, defaults = module.DownloaderPathMapping().get_form()
        # 使用已核对 FormRender 的相同表达式/事件上下文执行方式。
        script = r"""
const assert = require('node:assert/strict');
const { form, model } = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const fields = form[0].content;
const add = fields.find(item => item.text === '添加映射');
const remove = fields.find(item => item.text === '删除映射');
const selector = fields.find(item => item.props?.model === 'mapping_index');
const inputs = fields.filter(item => item.component === 'VTextField');
const event = (item, key, value) => new Function('model', 'event',
  `with(model) { return (${item.props[key]})(event); }`)(model, value);
const expression = value => new Function('model',
  `with(model) { return ${value.slice(2, -2).trim()} }`)(model);
const validateExpressions = () => {
  for (const item of fields) for (const value of Object.values(item.props || {}))
    if (typeof value === 'string' && value.startsWith('{{')) expression(value);
};
validateExpressions();
assert.equal(expression(remove.props.disabled), true);
for (const [windows, storage] of [['E:/Movies', '/movies'], ['F:/TV', 'smb:/tv'], ['G:/Temp', '/temp']]) {
  event(add, 'onClick');
  event(inputs[0], 'onUpdate:modelValue', windows);
  event(inputs[1], 'onUpdate:modelValue', storage);
  validateExpressions();
}
assert.equal(model.mappings.length, 3);
assert.equal(expression(selector.props.items)[1].title, '2. F:/TV → smb:/tv');
model.mapping_index = 1;
assert.equal(expression(inputs[0].props.modelValue), 'F:/TV');
event(inputs[1], 'onUpdate:modelValue', '/television');
assert.equal(model.mappings[0].storage_root, '/movies');
assert.equal(model.mappings[1].storage_root, '/television');
event(remove, 'onClick');
assert.equal(expression(inputs[0].props.modelValue), 'G:/Temp');
event(remove, 'onClick');
assert.equal(model.mapping_index, 0);
assert.equal(expression(inputs[0].props.modelValue), 'E:/Movies');
model.downloaders = ['Windows qB', 'Second qB'];
assert.deepEqual(JSON.parse(JSON.stringify(model)).mappings, model.mappings);
event(remove, 'onClick');
validateExpressions();
assert.equal(expression(remove.props.disabled), true);
event(add, 'onClick');
assert.equal(model.mapping_index, 0);
assert.deepEqual(model.mappings, [{windows_root: '', storage_root: ''}]);
"""
        result = subprocess.run([shutil.which("node"), "-e", script],
                                input=json.dumps({"form": form, "model": defaults}),
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
