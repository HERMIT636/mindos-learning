# 函数与返回值入门

原创公开教学示例，MIT 许可；内容状态：待教学审核。

## 把一个过程定义为函数

函数可以接收输入，并在调用时执行一段操作。例如，把一个数增加一：

```python
def increment(number):
    return number + 1

result = increment(4)
```

这里 `number` 是参数，调用中的 `4` 是传入的值。函数返回 `5`，因此 `result` 的值是 `5`。

## 返回与显示

`return` 将结果交给调用者，并结束本次函数执行。`print` 把内容写到输出中，通常用于显示信息。

```python
def show_increment(number):
    print(number + 1)

result = show_increment(4)
```

第二个例子会显示 `5`，但函数没有返回这个数，`result` 的值为 `None`。需要继续计算时，应明确返回所需的值。

## 自查

阅读函数时依次检查：接收哪些输入、执行哪些操作、返回什么值。看到屏幕输出并不能说明调用者取得了同样的返回值。

本材料与仓库中的公开练习配套，不用于正式学习效果评估。
