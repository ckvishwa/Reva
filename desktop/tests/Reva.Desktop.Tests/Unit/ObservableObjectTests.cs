using System.ComponentModel;
using Reva.Desktop.State;

namespace Reva.Desktop.Tests.Unit;

public class ObservableObjectTests
{
    private sealed class TestModel : ObservableObject
    {
        private string _name = string.Empty;

        public string Name
        {
            get => _name;
            set => SetProperty(ref _name, value);
        }
    }

    [Fact]
    public void SetProperty_RaisesPropertyChanged_WhenValueChanges()
    {
        var model = new TestModel();
        var raised = new List<string?>();
        model.PropertyChanged += (_, e) => raised.Add(e.PropertyName);

        model.Name = "REVA";

        Assert.Equal(new List<string?> { nameof(TestModel.Name) }, raised);
    }

    [Fact]
    public void SetProperty_DoesNotRaisePropertyChanged_WhenValueIsUnchanged()
    {
        var model = new TestModel { Name = "REVA" };
        var raised = new List<string?>();
        model.PropertyChanged += (_, e) => raised.Add(e.PropertyName);

        model.Name = "REVA";

        Assert.Empty(raised);
    }

    [Fact]
    public void SetProperty_UpdatesValue()
    {
        var model = new TestModel();

        model.Name = "REVA";

        Assert.Equal("REVA", model.Name);
    }
}
