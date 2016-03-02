import React from "react";
import ReactDOM from "react-dom";

const VirtualScrollMixin = (Component, defaultProps) => {

    let VScroll = class extends React.Component {
        constructor(props) {
            super(props);
            this.state = {
                start: 0,
                stop: 0
            };
        }

        componentDidMount() {
            this.onScroll();
            window.addEventListener('resize', this.onScroll);
        }

        componentWillUnmount() {
            window.removeEventListener('resize', this.onScroll);
        }

        get viewport() {
            return ReactDOM.findDOMNode(this);
        }

        onScroll() {
            const {rowHeight, rowHeightMin} = this.props;

            const viewport = this.viewport;
            const viewportTop = viewport.scrollTop;
            const viewportHeight = viewport.offsetHeight;
            const start = Math.floor(viewportTop / rowHeight);
            const stop = start + Math.ceil(viewportHeight / (rowHeightMin || rowHeight));

            this.setState({start, stop});
        }

        scrollRowIntoView(rowIndex) {
            const {rowHeight, headHeight} = this.props;

            const rowTop = (rowIndex * rowHeight) + headHeight;
            const rowBottom = rowTop + rowHeight;

            const viewport = this.viewport;
            const viewportTop = viewport.scrollTop;
            const viewportHeight = viewport.offsetHeight;
            const viewportBottom = viewportTop + viewportHeight;

            // Account for pinned thead
            if (rowTop - headHeight < viewportTop) {
                viewport.scrollTop = rowTop - headHeight;
            } else if (rowBottom > viewportBottom) {
                viewport.scrollTop = rowBottom - viewportHeight;
            }
        }

        renderPlaceholderTop() {
            // When a large trunk of elements is removed from the button, start may be far off the viewport.
            // To make this issue less severe, limit the top placeholder to the total number of rows.
            const height = Math.min(this.state.start, this.props.elements.length) * this.props.rowHeight;

            const spacer = <this.props.placeholder key="placeholder-top" style={{height}}/>;

            if (this.state.start % 2 === 1) {
                // fix even/odd row coloring
                return [spacer, <this.props.placeholder key="placeholder-top-2"/>];
            } else {
                return spacer;
            }
        }

        renderPlaceholderBottom() {
            const height = Math.max(0, this.props.elements.length - this.state.stop) * this.props.rowHeight;
            return <this.props.placeholder key="placeholder-bottom" style={{height}}/>;
        }

        render() {
            const {start, stop} = this.state;
            const elements = this.props.elements.slice(start, stop);
            return <Component
                placeholderTop={this.renderPlaceholderTop()}
                placeholderBottom={this.renderPlaceholderBottom()}
                {...this.props}
                onScroll={() => this.onScroll()}
                elements={elements}
            />;
        }

    };
    VScroll.propTypes = {
        elements: React.PropTypes.array.isRequired,
        placeholder: React.PropTypes.string.isRequired,
        rowHeight: React.PropTypes.number.isRequired,
        rowHeightMin: React.PropTypes.number,
        headHeight: React.PropTypes.number // We have a fixed table head overlaying parts of the table.
    };
    VScroll.defaultProps = defaultProps;
    return VScroll;
};

export default VirtualScrollMixin;

/*
This was an earlier attempt that turned out to be a bit spaghetti.

export default class VirtualScroll extends React.Component {
    constructor(props) {
        super(props);
        this.onScroll = this.onScroll.bind(this);
        this.state = {
            start: 0,
            stop: 0
        };
    }

    componentDidMount() {
        this.onScroll();
        window.addEventListener('resize', this.onScroll);
        this.viewport.addEventListener("scroll", this.onScroll);
    }

    componentWillUnmount() {
        window.removeEventListener('resize', this.onScroll);
        this.viewport.removeEventListener("scroll", this.onScroll);
    }

    get viewport() {
        return ReactDOM.findDOMNode(this.props.container);
    }

    onScroll() {
        const {rowHeight, rowHeightMin} = this.props;

        const viewport = this.viewport;
        const viewportTop = viewport.scrollTop;
        const viewportHeight = viewport.offsetHeight;
        const start = Math.floor(viewportTop / rowHeight);
        const stop = start + Math.ceil(viewportHeight / (rowHeightMin || rowHeight));

        this.setState({start, stop});
    }

    scrollRowIntoView(rowIndex) {
        const {rowHeight, headHeight} = this.props;

        const rowTop = (rowIndex * rowHeight) + headHeight;
        const rowBottom = rowTop + rowHeight;

        const viewport = this.viewport;
        const viewportTop = viewport.scrollTop;
        const viewportHeight = viewport.offsetHeight;
        const viewportBottom = viewportTop + viewportHeight;

        // Account for pinned thead
        if (rowTop - headHeight < viewportTop) {
            viewport.scrollTop = rowTop - headHeight;
        } else if (rowBottom > viewportBottom) {
            viewport.scrollTop = rowBottom - viewportHeight;
        }
    }

    get placeholderTag() {
        return this.props.tagName === "tbody" ? "tr" : this.props.tagName;
    }

    renderPlaceholderTop() {
        const Placeholder = this.placeholderTag;
        // When a large trunk of elements is removed from the button, start may be far off the viewport.
        // To make this issue less severe, limit the top placeholder to the total number of rows.
        const height = Math.min(this.state.start, this.props.elements.length) * this.props.rowHeight;

        const spacer = <Placeholder key="placeholder-top" style={{height}}/>;

        if (this.state.start % 2 === 1) {
            // fix even/odd row coloring
            return [spacer, <Placeholder key="placeholder-top-2"/>];
        } else {
            return spacer;
        }
    }

    renderPlaceholderBottom() {
        const Placeholder = this.placeholderTag;
        const height = Math.max(0, this.props.elements.length - this.state.stop) * this.props.rowHeight;
        return <Placeholder key="placeholder-bottom" style={{height}}/>;
    }

    renderRows() {
        const {elements, renderRow} = this.props;
        const max = Math.min(elements.length, this.state.stop);

        var rows = [];
        for (var i = this.state.start; i < max; i++) {
            rows.push(
                renderRow(elements[i])
            );
        }
        return rows;
    }

    render() {
        return <this.props.tagName>
            { this.renderPlaceholderTop() }
            { this.renderRows() }
            { this.renderPlaceholderBottom() }
        </this.props.tagName>;
    }

}
VirtualScroll.propTypes = {
    tagName: React.PropTypes.string.isRequired,
    container: React.PropTypes.element.isRequired,
    elements: React.PropTypes.array.isRequired,
    renderRow: React.PropTypes.func.isRequired,
    rowHeight: React.PropTypes.number.isRequired,
    rowHeightMin: React.PropTypes.number,
    headHeight: React.PropTypes.number // We have a fixed table head overlaying parts of the table.
};
VirtualScroll.defaultProps = {
    headHeight: 0
};
*/