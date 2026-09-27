# 函数与返回值入门

原创公开教学示例，MIT 许可；已完成项目内容复核，仍待教师／助教审核。

## 把一个过程定义为函数

函数可以接收输入，并在调用时执行一段操作。例如，把一个数增加一：

```python
def increment(number):
    return number + 1

result = increment(4)
```

这里 `number` 是函数定义中的**形参**，调用中的 `4` 是传入的**实参**。写下 `def` 语句会定义函数；写下 `increment(4)` 才会调用它。函数返回 `5`，因此 `result` 的值是 `5`。

## 返回与显示

`return` 将值交给调用者，并结束本次函数调用；`print` 把内容写到输出中，通常用于显示信息。**输出给人看**与**返回给调用者继续使用**是两件事。

```python
def show_increment(number):
    print(number + 1)

result = show_increment(4)
```

第二个例子会显示 `5`，但函数执行到末尾时没有执行 `return`，所以 `result` 的值为 `None`。`print(...)` 自身也不会把显示的内容当作所在函数的返回值；需要继续计算时，应明确返回所需的值。执行 `return` 而不写返回表达式时，也会返回 `None`。

## 自查

阅读函数时依次检查：接收哪些输入、执行哪些操作、返回什么值。看到屏幕输出并不能说明调用者取得了同样的返回值。

本材料与仓库中的公开练习配套，不用于正式学习效果评估。语言行为已对照 [Python 官方教程：定义函数](https://docs.python.org/3/tutorial/controlflow.html#defining-functions) 与 [Python 内置函数：print](https://docs.python.org/3/library/functions.html#print) 核对。
